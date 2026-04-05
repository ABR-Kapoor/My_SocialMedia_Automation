"""
Telegram Bot Handlers — all conversation flows and command handlers.
"""
import asyncio
import json
import logging
import os
import psycopg2
from datetime import datetime
from functools import wraps
from io import BytesIO

from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler, CommandHandler, ContextTypes,
    ConversationHandler, MessageHandler, filters,
)

from bot.keyboards import (
    cancel_keyboard, image_keyboard, image_style_keyboard,
    platform_keyboard, repo_keyboard, review_keyboard,
    schedule_keyboard, topic_keyboard,
)
from bot.memory import build_context_string, format_history_message, get_last_post_topic
from bot.states import (
    EDITING_CONTENT, ENTERING_DATETIME, REVIEWING_CONTENT,
    SELECTING_IMAGE, SELECTING_IMG_STYLE, SELECTING_PLATFORMS,
    SELECTING_REPO, SELECTING_SCHEDULE, SELECTING_TOPIC,
    UPDATING_STYLE, UPLOADING_IMAGE,
)
from config import IST, TELEGRAM_CHAT_ID, NEON_DATABASE_URL
from database.connection import get_pool
from database.models import (
    get_style_prefs, save_post, save_post_context,
    save_scheduled_post, upsert_style_prefs,
)
from agents.content_agent import ContentAgent as _ContentAgent
from agents.image_agent import ImageAgent as _ImageAgent
from agents.search_agent import SearchAgent as _SearchAgent
from agents.github_agent import GithubAgent as _GithubAgentClass
content_agent = _ContentAgent()
image_agent   = _ImageAgent()
search_agent  = _SearchAgent()
github_agent  = _GithubAgentClass()
from platforms.linkedin import LinkedInPlatform

from platforms.medium import MediumPlatform, MediumManualPostRequired
from platforms.twitter import TwitterPlatform, TwitterManualPostRequired
from platforms.reddit import RedditPlatform, RedditManualPostRequired
from platforms.github import GithubPlatform

logger = logging.getLogger(__name__)


# ── Owner-only guard ──────────────────────────────────────────────────────────

def owner_only(func):
    """Restrict handler to the bot owner (TELEGRAM_CHAT_ID)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else None
        if user_id != TELEGRAM_CHAT_ID:
            if update.message:
                await update.message.reply_text("⛔ Unauthorised.")
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


def _platform_name(key: str) -> str:
    return {"linkedin": "LinkedIn",
            "medium": "Medium", "github": "GitHub"}.get(key, key.capitalize())


def _ist_now() -> datetime:
    return datetime.now(IST)


def _escape_for_tg(text: str) -> str:
    """Escape Markdown special chars in AI content so Telegram doesn't choke.
    We use MarkdownV1 for the wrapper; content often has **, __, ## etc.
    Safest: strip Markdown from the display copy (actual post content stays untouched).
    """
    import re
    # Remove ## heading markers
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    # Escape *, _, `, [ characters so they're treated as literals
    text = re.sub(r'([*_`\[\]])', r'\\\1', text)
    return text


# ── /start ────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["user_id"] = update.effective_user.id
    await update.message.reply_text(
        "Abeer Brand Bot - social media\n\n"
        "/post — create & publish a post\n"
        "/github\\_commit — check & auto-commit to DSA-java\n"
        "/auth\\_linkedin — linkedin connection status\n"
        "/history — last 5 posts\n"
        "/style — writing tone",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /help ─────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


# ── /history ──────────────────────────────────────────────────────────────────

@owner_only
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Fetching post history…")
    history = await format_history_message()
    await msg.edit_text(history, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


# ── /style ────────────────────────────────────────────────────────────────────

@owner_only
async def cmd_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prefs = await get_style_prefs(update.effective_user.id)
    text = (
        f"🎨 *Current Style Settings*\n\n"
        f"Tone: `{prefs.get('tone', 'entrepreneur')}`\n"
        f"Custom notes: _{prefs.get('custom_notes', 'None')}_\n\n"
        "Send me a message describing your style override.\n"
        "Example: _'Be more casual, use Gen-Z slang, mention blockchain more'_\n\n"
        "Or type /cancel to keep current settings."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    return UPDATING_STYLE


async def receive_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = update.message.text.strip()
    uid   = update.effective_user.id
    await upsert_style_prefs(uid, "custom", notes)
    await update.message.reply_text(
        f"✅ *Style updated!* I'll write with this tone going forward:\n\n_{notes}_",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── /auth_linkedin ────────────────────────────────────────────────────────────

@owner_only
async def cmd_auth_linkedin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show LinkedIn connection status or initiate OAuth if not connected."""

    def _fetch_token():
        """Sync psycopg2 query — same driver that writes the token successfully."""
        db_url = NEON_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
        conn = psycopg2.connect(db_url)
        cur  = conn.cursor()
        cur.execute(
            "SELECT person_urn, extra_data, updated_at FROM oauth_tokens WHERE platform = 'linkedin'"
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row   # (person_urn, extra_data, updated_at) or None

    row   = None
    error = None
    try:
        row = await asyncio.get_event_loop().run_in_executor(None, _fetch_token)
    except Exception as e:
        error = str(e)
        logger.error(f"LinkedIn status DB query failed: {e}", exc_info=True)

    if error:
        await update.message.reply_text(
            f"⚠️ DB query error:\n`{error[:300]}`",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    if row:
        person_urn, extra_data_raw, updated_at = row
        # psycopg2 may return JSONB as dict or string depending on adapter
        if isinstance(extra_data_raw, dict):
            extra = extra_data_raw
        elif isinstance(extra_data_raw, str):
            try:
                extra = json.loads(extra_data_raw)
            except Exception:
                extra = {}
        else:
            extra = {}

        name        = extra.get("name", "") or person_urn or "Unknown"
        vanity_name = extra.get("vanity_name", "")
        urn         = person_urn or "n/a"
        updated     = updated_at.strftime("%d %b %Y, %H:%M IST") if updated_at else "unknown"

        # Build profile URL — vanityName gives direct link, ~ always goes to own profile
        profile_slug = vanity_name if vanity_name else "~"
        profile_url  = f"https://www.linkedin.com/in/{profile_slug}"
        profile_line = f"[👤 View LinkedIn Profile]({profile_url})\n\n"

        await update.message.reply_text(
            "🔷 *LinkedIn Status*\n\n"
            "Status: ✅ *Connected*\n"
            f"Account: *{name}*\n"
            f"ID: `{urn}`\n"
            f"Since: {updated}\n\n"
            f"{profile_line}"
            "Use /post to publish on LinkedIn.",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Reconnect / Switch Account", callback_data="reconnect_li")
            ]])
        )
        return

    # Not connected — show auth link
    li       = LinkedInPlatform()
    auth_url = li.get_auth_url(state="tg_auth")
    await update.message.reply_text(
        "🔷 *LinkedIn Status*\n\n"
        "Status: ❌ *Not connected*\n\n"
        "Click below to authenticate with your LinkedIn account:\n\n"
        f"[👉 Connect LinkedIn Account]({auth_url})\n\n"
        "_After approving, you'll get a confirmation message here._",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=False,
    )



# ── /github_commit ────────────────────────────────────────────────────────────

@owner_only
async def cmd_github_commit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's DSA-java commit status and offer a one-click auto-commit."""
    msg = await update.message.reply_text("⏳ Checking today's commits…")

    status = await asyncio.get_event_loop().run_in_executor(
        None, github_agent.check_today_commit
    )

    if status["committed"]:
        text = (
            "🐙 GitHub DSA-java — Today's Status\n\n"
            "✅ You've already committed today!\n"
            f"Count: {status['count']} commit(s)\n"
            f"Last: {status['last_msg']}\n\n"
            f"View Commit: {status['last_url']}"
        )
        buttons = [
            [InlineKeyboardButton("💬 Comment on existing file (comment and commit)", callback_data="gh_commit_comment")],
            [InlineKeyboardButton("📝 Create folder or/and file and write java code (Do DSA and Commit)", callback_data="gh_commit_dsa")],
        ]
    else:
        text = (
            "🐙 GitHub DSA-java — Today's Status\n\n"
            "❌ Yet to commit today!\n\n"
            "Hit the button below — I'll pick a Java file, "
            "generate a contextual insight, and commit it automatically. "
            "No input needed! 🚀"
        )
        buttons = [
            [InlineKeyboardButton("💬 Comment on existing file (comment and commit)", callback_data="gh_commit_comment")],
            [InlineKeyboardButton("📝 Create folder or/and file and write java code (Do DSA and Commit)", callback_data="gh_commit_dsa")],
        ]

    await msg.edit_text(
        text,
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def gh_commit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Auto-commit to DSA-java — distinct modes depending on button click:
    A: add inline // comment to an existing Java file
    B: create new folder + Java file for a DSA topic
    """
    query = update.callback_query
    await query.answer()

    mode = "A" if query.data == "gh_commit_comment" else "B"

    # ── MODE A: Inline comment in existing file ────────────────────────────────
    if mode == "A":
        await query.edit_message_text("⏳ Picking a Java file to review…")

        file_info = await asyncio.get_event_loop().run_in_executor(
            None, github_agent.get_random_java_file
        )
        if not file_info:
            await query.edit_message_text("⚠️ Couldn't fetch files from DSA-java. Check GITHUB_PAT.")
            return

        await query.edit_message_text(
            f"📂 {file_info['path']}\n\n⏳ Writing inline comments…",
        )

        prompt = f"""You're a developer reviewing your own Java DSA code from a few days ago.
Add 2-4 inline // comment lines to clarify a part of this file.

FILE: {file_info['name']}
CONTENT:
{file_info['preview'][:2500]}

Rules:
- Comments must feel personal, like you just re-read the code
- Reference actual lines/logic you see (algorithm name, a variable, a loop)
- Good examples:
  // O(n log n) — the merge step is what's expensive here
  // tried doing this recursively first, ran into stack overflow on n>10k
  // edge case: empty list returns 0 directly, don't want NPE downstream
  // realised the inner loop can start from i+1, saves ~half iterations
- Return ONLY the comment lines (2-4 lines starting with //)
- No explanation, no code, just the comment lines
"""
        try:
            resp = await content_agent.model.generate_content_async(prompt)
            comment_lines = resp.text.strip()
        except Exception as e:
            logger.error(f"AI comment failed: {e}")
            comment_lines = f"// revisited this — logic looks fine, just adding a note for clarity\n// time complexity here should be O(n log n) overall"

        await query.edit_message_text(
            f"📂 {file_info['path']}\n\n"
            f"💬 Comments preview:\n{comment_lines[:300]}\n\n"
            "⏳ Committing…",
        )

        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: github_agent.commit_inline_comment(file_info, comment_lines)
        )

    # ── MODE B: Create new DSA topic Java file ─────────────────────────────────
    else:
        await query.edit_message_text("⏳ Picking a DSA topic to implement…")

        folder, filename, description = await asyncio.get_event_loop().run_in_executor(
            None, github_agent.pick_new_dsa_topic
        )

        await query.edit_message_text(
            f"📌 Topic: {description}\n\n⏳ Writing Java code…",
        )

        prompt = f"""Write a complete Java implementation of: {description}
Class name: {filename}
Folder context: {folder}

Rules (strictly follow):
- Real student-quality code, not textbook. Natural variable names.
- Include a main() with 2-3 test cases and System.out.println output
- Add 2-3 inline comments that feel personal:
  // tried recursive first but iterative is cleaner here
  // O(n) space because of the stack, acceptable for now
  // this edge case tripped me up — empty array must return -1
- No package declaration
- Full working Java code only — no markdown, no explanation outside comments
- Make it feel like something a student pushed after solving a problem
"""
        try:
            resp = await content_agent.model.generate_content_async(prompt)
            java_code = resp.text.strip()
            # Strip markdown code fences if model wraps in ```java
            if java_code.startswith("```"):
                lines = java_code.splitlines()
                java_code = "\n".join(
                    ln for ln in lines
                    if not ln.strip().startswith("```")
                )
        except Exception as e:
            logger.error(f"Java code generation failed: {e}")
            java_code = (
                f"// {description}\n"
                f"public class {filename} {{\n"
                f"    public static void main(String[] args) {{\n"
                f"        // TODO: implement\n"
                f"        System.out.println(\"Work in progress\");\n"
                f"    }}\n"
                f"}}\n"
            )

        await query.edit_message_text(
            f"📌 {description}\n\n"
            f"📄 File: {folder}/{filename}.java\n\n"
            "⏳ Committing to DSA-java…",
        )

        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: github_agent.create_dsa_file(folder, filename, java_code, description)
        )

    # ── Show result ────────────────────────────────────────────────────────────
    if result["success"]:
        mode_icon = "📝" if mode == "A" else "🆕"
        mode_label = "Inline comment added" if mode == "A" else "New file created"
        await query.edit_message_text(
            f"✅ Committed to DSA-java!\n\n"
            f"{mode_icon} {mode_label}\n"
            f"📂 {result['file']}\n"
            f"💬 {result['message']}\n\n"
            f"View Commit: {result['url']}",
            disable_web_page_preview=True,
        )
    else:
        await query.edit_message_text(
            f"❌ Commit failed:\n{result['message'][:300]}",
        )


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN POST FLOW — 7 STEPS
# ═══════════════════════════════════════════════════════════════════════════════

# ── STEP 1: /post — Platform Selection ───────────────────────────────────────

@owner_only
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point — start the post creation flow."""
    context.user_data.clear()
    context.user_data["selected_platforms"] = set()
    context.user_data["image_bytes"]        = None
    context.user_data["content"]            = {}
    context.user_data["hashtags"]           = []
    context.user_data["review_idx"]         = 0

    await update.message.reply_text(
        "🚀 *Let's create a post!*\n\n"
        "Step 1/6 — *Where do you want to post?*\n"
        "_(Tap to toggle, then hit ✔️ Confirm)_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=platform_keyboard(set()),
    )
    return SELECTING_PLATFORMS


async def platform_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.replace("plt_", "")
    selected: set = context.user_data.setdefault("selected_platforms", set())
    if key in selected:
        selected.discard(key)
    else:
        selected.add(key)
    await query.edit_message_reply_markup(platform_keyboard(selected))
    return SELECTING_PLATFORMS


async def platform_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected: set = context.user_data.get("selected_platforms", set())

    if not selected:
        await query.answer("⚠️ Select at least one platform!", show_alert=True)
        return SELECTING_PLATFORMS

    platform_list = ", ".join(_platform_name(p) for p in selected)
    last_topic    = await get_last_post_topic()
    context.user_data["last_topic"] = last_topic

    text = f"✅ Posting to: *{platform_list}*\n\nStep 2/6 — *What's the topic?*\n\n"
    if last_topic:
        text += f"💬 Last post was about: _{last_topic[:80]}_\n"

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=topic_keyboard(last_topic=last_topic))
    return SELECTING_TOPIC


# ── STEP 2: Topic ─────────────────────────────────────────────────────────────

async def topic_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = update.message.text.strip()
    if not topic:
        await update.message.reply_text("Please type your topic:", reply_markup=cancel_keyboard())
        return SELECTING_TOPIC
    context.user_data["topic"] = topic
    await update.message.reply_text(
        "Step 3/6 — *Image?*\n\nDo you want an image with this post?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=image_keyboard(),
    )
    return SELECTING_IMAGE


async def topic_last_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    topic = context.user_data.get("last_topic")
    if not topic:
        await query.answer("⚠️ No previous topic found!", show_alert=True)
        return SELECTING_TOPIC
        
    context.user_data["topic"] = topic
    await query.edit_message_text(
        f"✅ Using topic: *{topic[:50]}...*\n\nStep 3/6 — *Image?*\n\nDo you want an image with this post?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=image_keyboard(),
    )
    return SELECTING_IMAGE

async def topic_repos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ Fetching your GitHub repos…")

    repos = await asyncio.get_event_loop().run_in_executor(None, github_agent.get_user_repos)
    context.user_data["repos"] = repos

    if not repos:
        await query.edit_message_text("⚠️ Couldn't fetch repos. Please type your topic:",
                                      reply_markup=cancel_keyboard())
        return SELECTING_TOPIC

    text = "📂 *Your GitHub Repos* — pick one to write about:\n\n"
    text += github_agent.format_repos_for_display(repos)
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=repo_keyboard(repos))
    return SELECTING_REPO


async def topic_ai_suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("⏳ Searching web for tech & startup trends to inspire topics…")
    
    try:
        web_context = await search_agent.search_web_for_topic("latest startup tech india AI trends news")
    except Exception:
        web_context = ""

    await query.edit_message_text("⏳ Generating topic ideas…")
    repos       = await asyncio.get_event_loop().run_in_executor(None, github_agent.get_user_repos)
    suggestions = await content_agent.suggest_topics(repos, [], web_context=web_context)
    context.user_data["suggestions"] = suggestions

    await query.edit_message_text(
        "💡 *AI Topic Suggestions:*\n\nPick one or type your own below:\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=topic_keyboard(suggestions),
    )
    return SELECTING_TOPIC


async def topic_suggestion_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx         = int(query.data.replace("topic_sug_", ""))
    suggestions = context.user_data.get("suggestions", [])
    if idx < len(suggestions):
        topic = suggestions[idx].lstrip("🚀💡🌐🤖📈 ").strip()
        context.user_data["topic"] = topic
        await query.edit_message_text(
            f"✅ Topic: *{topic}*\n\nStep 3/6 — *Image?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=image_keyboard(),
        )
        return SELECTING_IMAGE
    return SELECTING_TOPIC


async def repo_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx   = int(query.data.replace("repo_", ""))
    repos = context.user_data.get("repos", [])
    if idx >= len(repos):
        return SELECTING_REPO

    repo  = repos[idx]
    topic = f"Building / story behind '{repo['name']}' — {repo.get('description', '')} ({repo['language']})"
    context.user_data["topic"] = topic

    await query.edit_message_text(
        f"✅ Writing about: *{repo['name']}*\n\nStep 3/6 — *Image?*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=image_keyboard(),
    )
    return SELECTING_IMAGE


# ── STEP 3: Image ─────────────────────────────────────────────────────────────

async def image_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🎨 *Choose image style:*", parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=image_style_keyboard())
    return SELECTING_IMG_STYLE


async def image_style_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    style = query.data.replace("style_", "")

    if style == "custom":
        await query.edit_message_text("✏️ Describe the image you want (1-2 sentences):",
                                      reply_markup=cancel_keyboard())
        context.user_data["awaiting_custom_img"] = True
        return UPLOADING_IMAGE

    await query.edit_message_text("⏳ Generating image… this takes ~15 seconds")
    topic = context.user_data.get("topic", "entrepreneurship and tech")
    try:
        img_bytes, _ = await image_agent.generate(topic, style=style)
        context.user_data["image_bytes"] = img_bytes
        await query.message.reply_photo(photo=BytesIO(img_bytes), caption="✅ Image ready!")
    except Exception as e:
        await query.message.reply_text(f"⚠️ Image generation failed: {e}\nContinuing without image.")

    await _proceed_to_generation(query.message, context)
    return REVIEWING_CONTENT


async def image_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("📁 Send me your image now (as a photo or file):",
                                  reply_markup=cancel_keyboard())
    return UPLOADING_IMAGE


async def receive_uploaded_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_custom_img") and update.message.text:
        custom_prompt = update.message.text.strip()
        context.user_data.pop("awaiting_custom_img", None)
        msg   = await update.message.reply_text("⏳ Generating image…")
        topic = context.user_data.get("topic", "entrepreneurship")
        try:
            img_bytes, _ = await image_agent.generate(topic, custom_prompt=custom_prompt)
            context.user_data["image_bytes"] = img_bytes
            await update.message.reply_photo(BytesIO(img_bytes), caption="✅ Image ready!")
        except Exception as e:
            await msg.edit_text(f"⚠️ Image generation failed: {e}")
        await _proceed_to_generation(update.message, context)
        return REVIEWING_CONTENT

    if update.message.photo:
        photo = update.message.photo[-1]
        f     = await photo.get_file()
        buf   = BytesIO()
        await f.download_to_memory(buf)
        context.user_data["image_bytes"] = buf.getvalue()
        await update.message.reply_text("✅ Image received!")
        await _proceed_to_generation(update.message, context)
        return REVIEWING_CONTENT

    await update.message.reply_text("Please send a photo or describe the image:")
    return UPLOADING_IMAGE


async def image_none(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["image_bytes"] = None
    await query.edit_message_text("⏳ Generating content for all platforms…")
    await _proceed_to_generation(query.message, context)
    return REVIEWING_CONTENT


# ── STEP 4: Generate Content ──────────────────────────────────────────────────

async def _proceed_to_generation(message, context: ContextTypes.DEFAULT_TYPE):
    topic     = context.user_data.get("topic", "")
    platforms = list(context.user_data.get("selected_platforms", []))
    uid       = context.user_data.get("user_id", TELEGRAM_CHAT_ID)

    prefs         = await get_style_prefs(uid)
    style_notes   = prefs.get("custom_notes", "")
    chain_context = await build_context_string()

    try:
        trending = await asyncio.get_event_loop().run_in_executor(
            None, lambda: search_agent.get_trending_hashtags(topic)
        )
    except Exception:
        trending = []

    generating_msg = await message.reply_text(
        "⏳ *Generating content…*\nCrafting your entrepreneur-style posts…",
        parse_mode=ParseMode.MARKDOWN,
    )

    web_context = ""
    # Only do web search if we are not restricted to GitHub or if it's explicitly asked/current affairs
    # Using a simple heuristic: if it contains words suggesting news/latest/current
    if any(w in topic.lower() for w in ["latest", "news", "current", "update", "today", "recent", "trend"]):
        web_context = await search_agent.search_web_for_topic(topic)

    if "github" in platforms:
        try:
            commit_info = await asyncio.get_event_loop().run_in_executor(
                None, github_agent.get_latest_commit_info
            )
            if commit_info:
                chain_context = (
                    chain_context + "\n"
                    f"Latest commit: {commit_info['message']} "
                    f"(files: {', '.join(commit_info['files'][:3])})"
                ).strip()
                context.user_data["github_commit"] = commit_info
        except Exception:
            pass
    content  = await content_agent.generate(
        topic=topic, platforms=platforms,
        context=chain_context, style_override=style_notes,
        web_context=web_context
    )
    
    # Check for known GitHub repos and append explicit links if mentioned.
    user_repos = context.user_data.get("repos")
    if "github_commit" in context.user_data or "github" in platforms or user_repos:
        try:
            repo_list = user_repos if user_repos else await asyncio.get_event_loop().run_in_executor(None, github_agent.get_user_repos)
            repo_names = {r["name"].lower(): r["name"] for r in repo_list}
            
            for plat, txt in content.items():
                appended_links = set()
                txt_lower = txt.lower()
                for r_low, r_exact in repo_names.items():
                    if r_low in txt_lower and r_exact.lower() not in appended_links:
                        link_text = f"\n\n🔗 Source: https://github.com/ABR-Kapoor/{r_exact}"
                        if link_text not in txt:
                            content[plat] += link_text
                            appended_links.add(r_exact.lower())
        except Exception as e:
            logger.warning(f"Error appending repo links: {e}")
            
    hashtags = await content_agent.generate_hashtags(topic, trending)

    context.user_data["content"]            = content
    context.user_data["hashtags"]           = hashtags
    context.user_data["review_idx"]         = 0
    context.user_data["approved_platforms"] = set()

    await generating_msg.delete()
    await _show_review(message, context)


async def _show_review(message, context: ContextTypes.DEFAULT_TYPE):
    platforms = list(context.user_data.get("selected_platforms", []))
    content   = context.user_data.get("content", {})
    hashtags  = context.user_data.get("hashtags", [])
    idx       = context.user_data.get("review_idx", 0)

    if not platforms:
        return

    current_platform = platforms[idx]
    current_content  = content.get(current_platform, "")
    platform_label   = _platform_name(current_platform)
    total            = len(platforms)
    tags_str         = " ".join(hashtags[:6]) if hashtags else ""

    # Telegram hard limit is 4096 chars — truncate preview content safely
    display_content = current_content
    if len(display_content) > 3200:
        display_content = display_content[:3200] + "\n[... truncated for preview]"

    # Escape AI-generated markdown chars before inserting into Telegram Markdown wrapper
    display_content = _escape_for_tg(display_content)

    text = (
        f"📋 *Review Content*\n\n"
        f"Platform {idx+1}/{total}: *{platform_label}*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{display_content}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if tags_str:
        text += f"Hashtags: {tags_str}\n"

    img_bytes = context.user_data.get("image_bytes")

    if img_bytes:
        try:
            from io import BytesIO
            await message.reply_photo(
                photo=BytesIO(img_bytes),
                caption=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=review_keyboard(platforms, idx, context.user_data.get("approved_platforms", set())),
            )
            return
        except Exception as e:
            logger.error(f"Failed to display image in review: {e}")

    await message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=review_keyboard(platforms, idx, context.user_data.get("approved_platforms", set())),
        disable_web_page_preview=True,
    )


# ── STEP 5: Review + Edit ────────────────────────────────────────────────────

async def review_prev(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    idx = max(0, context.user_data.get("review_idx", 0) - 1)
    context.user_data["review_idx"] = idx
    await query.delete_message()
    await _show_review(query.message, context)
    return REVIEWING_CONTENT


async def review_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    platforms = list(context.user_data.get("selected_platforms", []))
    idx       = min(len(platforms) - 1, context.user_data.get("review_idx", 0) + 1)
    context.user_data["review_idx"] = idx
    await query.delete_message()
    await _show_review(query.message, context)
    return REVIEWING_CONTENT


async def review_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    platforms = list(context.user_data.get("selected_platforms", []))
    idx       = context.user_data.get("review_idx", 0)
    platform  = platforms[idx] if platforms else "content"

    await query.edit_message_text(
        f"✏️ *Editing {_platform_name(platform)}*\n\n"
        "Tell me what to change:\n"
        "_Examples: \"Make it shorter\", \"Add more blockchain angle\", "
        "\"Use a stronger hook\", \"More casual tone\"_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_keyboard(),
    )
    return EDITING_CONTENT


async def receive_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction  = update.message.text.strip()
    platforms    = list(context.user_data.get("selected_platforms", []))
    idx          = context.user_data.get("review_idx", 0)
    platform     = platforms[idx] if platforms else "linkedin"
    topic        = context.user_data.get("topic", "")
    prev_content = context.user_data["content"].get(platform, "")

    msg         = await update.message.reply_text("⏳ Rewriting…")
    new_content = await content_agent.regenerate(topic, platform, prev_content, instruction)
    context.user_data["content"][platform] = new_content
    
    # Remove from approved so user reviews edit
    if "approved_platforms" in context.user_data:
        context.user_data["approved_platforms"].discard(platform)

    await msg.delete()
    await _show_review(update.message, context)
    return REVIEWING_CONTENT


async def review_regen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query     = update.callback_query
    await query.answer()
    platforms = list(context.user_data.get("selected_platforms", []))
    idx       = context.user_data.get("review_idx", 0)
    platform  = platforms[idx] if platforms else "linkedin"
    topic     = context.user_data.get("topic", "")

    await query.edit_message_text(f"⏳ Generating fresh version for {_platform_name(platform)}…")
    new = await content_agent.generate(topic=topic, platforms=[platform], context="", style_override="")
    context.user_data["content"][platform] = new.get(platform, "")
    
    # Remove from approved so user reviews regenerated content
    if "approved_platforms" in context.user_data:
        context.user_data["approved_platforms"].discard(platform)

    await query.delete_message()
    await _show_review(query.message, context)
    return REVIEWING_CONTENT


async def review_approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    platforms          = list(context.user_data.get("selected_platforms", []))
    idx                = context.user_data.get("review_idx", 0)
    approved_platforms = context.user_data.setdefault("approved_platforms", set())
    
    if idx < len(platforms):
        current_platform = platforms[idx]
        approved_platforms.add(current_platform)
        
    if len(approved_platforms) >= len(platforms):
        # All selected platforms are approved
        await query.edit_message_text(
            "✅ *All Content Approved!*\n\nStep 6/6 — *When should this go out?*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=schedule_keyboard(),
        )
        return SELECTING_SCHEDULE
    else:
        # Move to the next unapproved platform
        next_unapproved_idx = next(
            (i for i, p in enumerate(platforms) if p not in approved_platforms),
            idx
        )
        context.user_data["review_idx"] = next_unapproved_idx
        await query.delete_message()
        await _show_review(query.message, context)
        return REVIEWING_CONTENT


# ── STEP 6: Schedule ────────────────────────────────────────────────────────

async def schedule_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚀 *Posting to all platforms…* Please wait.",
                                  parse_mode=ParseMode.MARKDOWN)
    results = await _execute_posting(context)
    await query.message.reply_text(
        _format_results(results),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def schedule_later(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    now = _ist_now().strftime("%d %b %Y %H:%M")
    await query.edit_message_text(
        f"⏰ *Schedule Post*\n\nCurrent IST time: `{now}`\n\n"
        "Send me the date and time in this format:\n"
        "`DD Mon YYYY HH:MM` — e.g. `26 Feb 2026 09:00`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=cancel_keyboard(),
    )
    return ENTERING_DATETIME


async def receive_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        dt_naive = datetime.strptime(text, "%d %b %Y %H:%M")
        dt_ist   = dt_naive.replace(tzinfo=IST)
        if dt_ist <= _ist_now():
            await update.message.reply_text("⚠️ That time is in the past! Send a future time:")
            return ENTERING_DATETIME
    except ValueError:
        await update.message.reply_text(
            "⚠️ Invalid format. Use `DD Mon YYYY HH:MM`\nExample: `26 Feb 2026 09:00`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ENTERING_DATETIME

    topic     = context.user_data.get("topic", "")
    platforms = list(context.user_data.get("selected_platforms", []))
    content   = context.user_data.get("content", {})
    img_bytes = context.user_data.get("image_bytes")

    await save_scheduled_post(
        topic=topic, scheduled_time=dt_ist, platforms=platforms,
        content_linkedin=content.get("linkedin", ""),
        content_medium=content.get("medium", ""),
        content_github=content.get("github", ""),
        content_twitter=content.get("twitter", ""),
        content_reddit=content.get("reddit", ""),
        image_url="",
        image_data=img_bytes,
    )

    try:
        from scheduler.post_scheduler import schedule_post
        schedule_post(context, dt_ist)
    except Exception as e:
        logger.warning(f"APScheduler not available: {e}")

    time_str = dt_ist.strftime("%d %b %Y at %H:%M IST")
    await update.message.reply_text(
        f"✅ *Post scheduled!*\n\n📅 Will publish on: *{time_str}*\n\n"
        "I'll notify you when it goes live.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


# ── STEP 7: Execute Posting ──────────────────────────────────────────────────

async def _execute_posting(context) -> dict[str, str]:
    platforms = list(context.user_data.get("selected_platforms", []))
    content   = context.user_data.get("content", {})
    img_bytes = context.user_data.get("image_bytes")
    topic     = context.user_data.get("topic", "")
    hashtags  = context.user_data.get("hashtags", [])

    results: dict[str, str] = {}
    urls:    dict[str, str] = {}
    draft_image_sent = False

    platform_map = {
        "linkedin": LinkedInPlatform(),
        "medium":   MediumPlatform(),
        "twitter":  TwitterPlatform(),
        "reddit":   RedditPlatform(),
        "github":   GithubPlatform(),
    }

    for platform in platforms:
        handler      = platform_map.get(platform)
        if not handler:
            results[platform] = "⚠️ Unknown platform"
            continue

        post_content = content.get(platform, "")
        if platform == "linkedin" and hashtags:
            tag_str = " ".join(hashtags[:6])
            if tag_str not in post_content:
                post_content += f"\n\n{tag_str}"

        try:
            url = await handler.post(post_content, img_bytes)
            results[platform] = url
            urls[platform]    = url
            logger.info(f"✅ Posted to {platform}: {url}")
        except (MediumManualPostRequired, TwitterManualPostRequired, RedditManualPostRequired) as e:
            # Platform API locked/manual — send draft to Telegram for manual publish
            results[platform] = "📋 Draft sent to Telegram"
            logger.info(f"{platform} draft forwarded to Telegram: {e.title}")
            try:
                from telegram import Update as TGUpdate
                from config import TELEGRAM_CHAT_ID
                
                if img_bytes and not draft_image_sent:
                    await context.bot.send_photo(
                        chat_id=TELEGRAM_CHAT_ID,
                        photo=img_bytes,
                        caption="🖼️ *Image for your draft(s) is here!*",
                        parse_mode="Markdown"
                    )
                    draft_image_sent = True

                await context.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=e.telegram_text,
                    parse_mode="Markdown",
                    disable_web_page_preview=False,
                )
            except Exception as send_err:
                logger.error(f"Failed to forward {platform} draft: {send_err}")
        except Exception as e:
            results[platform] = f"❌ Failed: {e}"
            logger.error(f"Post to {platform} failed: {e}")

    try:
        await save_post(
            topic=topic, platforms=platforms,
            content_linkedin=content.get("linkedin", ""),
            content_medium=content.get("medium", ""),
            content_github=content.get("github", ""),
            content_twitter=content.get("twitter", ""),
            content_reddit=content.get("reddit", ""),
            image_data=img_bytes,
            hashtags=hashtags,
            linkedin_url=urls.get("linkedin", ""),
            medium_url=urls.get("medium", ""),
            github_url=urls.get("github", ""),
            twitter_url=urls.get("twitter", ""),
            reddit_url=urls.get("reddit", ""),
            status="published",
        )
        summary = f"Posted about '{topic}' on {', '.join(platforms)}"
        await save_post_context(summary, topic, platforms)
    except Exception as e:
        logger.error(f"DB save failed: {e}")

    return results


def _format_results(results: dict[str, str]) -> str:
    icons = {"linkedin": "🔷", "medium": "📝", "github": "🐙", "twitter": "🐦", "reddit": "👽"}
    lines = ["🎉 *Posted Successfully!*\n"]
    for platform, url in results.items():
        icon = icons.get(platform, "📌")
        if url.startswith("http"):
            lines.append(f"{icon} *{platform.capitalize()}*: [View Post]({url})")
        else:
            lines.append(f"{icon} *{platform.capitalize()}*: {url}")
    return "\n".join(lines)


# ── CANCEL / FALLBACK ─────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    msg = "🗑️ Post creation cancelled."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(msg)
    elif update.message:
        await update.message.reply_text(msg)
    return ConversationHandler.END


# ═══════════════════════════════════════════════════════════════════════════════
#  CONVERSATION HANDLER BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("post", cmd_post)],
        states={
            SELECTING_PLATFORMS: [
                CallbackQueryHandler(platform_toggle,  pattern="^plt_(?!confirm)"),
                CallbackQueryHandler(platform_confirm, pattern="^plt_confirm$"),
            ],
            SELECTING_TOPIC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, topic_text_input),
                CallbackQueryHandler(topic_repos,           pattern="^topic_repos$"),
                CallbackQueryHandler(topic_ai_suggest,      pattern="^topic_ai$"),
                CallbackQueryHandler(topic_suggestion_pick, pattern="^topic_sug_"),
                CallbackQueryHandler(topic_last_pick,       pattern="^topic_last$"),
            ],
            SELECTING_REPO: [
                CallbackQueryHandler(repo_pick,   pattern="^repo_"),
                CallbackQueryHandler(topic_repos, pattern="^topic_back$"),
            ],
            SELECTING_IMAGE: [
                CallbackQueryHandler(image_ai,     pattern="^img_ai$"),
                CallbackQueryHandler(image_upload, pattern="^img_upload$"),
                CallbackQueryHandler(image_none,   pattern="^img_none$"),
            ],
            SELECTING_IMG_STYLE: [
                CallbackQueryHandler(image_style_pick, pattern="^style_"),
            ],
            UPLOADING_IMAGE: [
                MessageHandler(filters.PHOTO, receive_uploaded_image),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_uploaded_image),
            ],
            REVIEWING_CONTENT: [
                CallbackQueryHandler(review_prev,    pattern="^rv_prev$"),
                CallbackQueryHandler(review_next,    pattern="^rv_next$"),
                CallbackQueryHandler(review_edit,    pattern="^rv_edit$"),
                CallbackQueryHandler(review_regen,   pattern="^rv_regen$"),
                CallbackQueryHandler(review_approve, pattern="^rv_approve$"),
                CallbackQueryHandler(cancel,         pattern="^rv_cancel$"),
            ],
            EDITING_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit),
            ],
            SELECTING_SCHEDULE: [
                CallbackQueryHandler(schedule_now,    pattern="^sched_now$"),
                CallbackQueryHandler(schedule_later,  pattern="^sched_later$"),
                CallbackQueryHandler(review_approve,  pattern="^sched_back$"),
            ],
            ENTERING_DATETIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_datetime),
            ],
            UPDATING_STYLE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_style),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^cancel$"),
        ],
        allow_reentry=True,
        per_message=False,
        per_chat=True,
        name="post_flow",
    )


def register_all_handlers(app):
    """Register all handlers on the Application object."""
    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("help",          cmd_help))
    app.add_handler(CommandHandler("history",       cmd_history))
    app.add_handler(CommandHandler("auth_linkedin", cmd_auth_linkedin))

    app.add_handler(CommandHandler("github_commit", cmd_github_commit))

    # Callback: GitHub auto-commit button
    app.add_handler(CallbackQueryHandler(gh_commit_action, pattern="^gh_commit_"))

    style_conv = ConversationHandler(
        entry_points=[CommandHandler("style", cmd_style)],
        states={UPDATING_STYLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_style)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(style_conv)
    app.add_handler(build_conversation_handler())
