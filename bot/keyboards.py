"""
Inline keyboards for the Telegram bot conversation flow.
All keyboards are built as InlineKeyboardMarkup objects.
"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ── STEP 1: PLATFORM SELECTION ────────────────────────────────────────────────

PLATFORMS = {
    "linkedin": "🔷 LinkedIn",
    "medium":   "📝 Medium",
    "twitter":  "🐦 Twitter/X",
    "reddit":   "👽 Reddit",
}


def platform_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    """Multi-select platform checkboxes. Selected = ✅ prefix."""
    buttons = []
    for key, label in PLATFORMS.items():
        check = "✅ " if key in selected else "☐ "
        buttons.append([InlineKeyboardButton(
            f"{check}{label}", callback_data=f"plt_{key}"
        )])
    buttons.append([InlineKeyboardButton("✔️ Confirm Platforms", callback_data="plt_confirm")])
    return InlineKeyboardMarkup(buttons)


# ── STEP 2: TOPIC SELECTION ───────────────────────────────────────────────────

def topic_keyboard(suggestions: list[str] | None = None, last_topic: str | None = None) -> InlineKeyboardMarkup:
    """Topic input prompt with AI suggestions, repo option, and previous topic."""
    buttons = []
    if last_topic:
        buttons.append([InlineKeyboardButton(f"🔁 Use: {last_topic[:40]}", callback_data="topic_last")])

    buttons.extend([
        [InlineKeyboardButton("📂 Suggest from my GitHub repos", callback_data="topic_repos")],
        [InlineKeyboardButton("💡 AI suggest topics for me",     callback_data="topic_ai")],
    ])
    if suggestions:
        for i, s in enumerate(suggestions[:5]):
            label = s[:55] + "…" if len(s) > 55 else s
            buttons.append([InlineKeyboardButton(label, callback_data=f"topic_sug_{i}")])
    return InlineKeyboardMarkup(buttons)


def repo_keyboard(repos: list[dict]) -> InlineKeyboardMarkup:
    """List of user's GitHub repos to pick a topic from."""
    buttons = []
    for i, r in enumerate(repos[:10]):
        label = f"{'⭐' if r['stars'] > 0 else '📁'} {r['name']} ({r['language']})"
        buttons.append([InlineKeyboardButton(label[:60], callback_data=f"repo_{i}")])
    buttons.append([InlineKeyboardButton("◀️ Back", callback_data="topic_back")])
    return InlineKeyboardMarkup(buttons)


def chain_keyboard() -> InlineKeyboardMarkup:
    """Ask if user wants to chain with a previous post."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 Continue last story", callback_data="chain_yes"),
        InlineKeyboardButton("🆕 Fresh post",          callback_data="chain_no"),
    ]])


# ── STEP 3: IMAGE SELECTION ───────────────────────────────────────────────────

def image_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 AI Generate Image",  callback_data="img_ai")],
        [InlineKeyboardButton("📁 Upload My Own",      callback_data="img_upload")],
        [InlineKeyboardButton("❌ No Image",           callback_data="img_none")],
    ])


def image_style_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔥 Bold Entrepreneur",  callback_data="style_entrepreneurial")],
        [InlineKeyboardButton("⚡ Tech Minimal",       callback_data="style_tech_minimal")],
        [InlineKeyboardButton("🌌 Creative Dark",      callback_data="style_creative_dark")],
        [InlineKeyboardButton("✏️ Custom Describe",    callback_data="style_custom")],
    ])


# ── STEP 5: CONTENT REVIEW ────────────────────────────────────────────────────

def review_keyboard(platforms: list[str], current_idx: int, approved_platforms: set[str] | None = None) -> InlineKeyboardMarkup:
    """Review buttons — navigate platforms, edit, regenerate, approve."""
    if approved_platforms is None:
        approved_platforms = set()

    nav = []
    if current_idx > 0:
        nav.append(InlineKeyboardButton("◀️ Prev",  callback_data="rv_prev"))
    if current_idx < len(platforms) - 1:
        nav.append(InlineKeyboardButton("▶️ Next",  callback_data="rv_next"))

    buttons = []
    if nav:
        buttons.append(nav)

    current_platform = platforms[current_idx]
    is_approved      = current_platform in approved_platforms

    approve_btn = InlineKeyboardButton("✅ Approved (Next)", callback_data="rv_approve") \
                  if is_approved \
                  else InlineKeyboardButton(f"✅ Approve {_platform_name(current_platform)}", callback_data="rv_approve")

    buttons += [
        [
            InlineKeyboardButton("✏️ Edit",        callback_data="rv_edit"),
            InlineKeyboardButton("🔄 Regenerate",  callback_data="rv_regen"),
        ],
        [approve_btn],
        [InlineKeyboardButton("🗑️ Cancel",          callback_data="rv_cancel")],
    ]
    return InlineKeyboardMarkup(buttons)
    
def _platform_name(platform_key: str) -> str:
    return PLATFORMS.get(platform_key, platform_key.title())


# ── STEP 6: SCHEDULE ──────────────────────────────────────────────────────────

def schedule_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Post Now",   callback_data="sched_now")],
        [InlineKeyboardButton("⏰ Schedule",   callback_data="sched_later")],
        [InlineKeyboardButton("◀️ Back",       callback_data="sched_back")],
    ])


# ── MISC ──────────────────────────────────────────────────────────────────────

def confirm_keyboard(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes", callback_data=yes_data),
        InlineKeyboardButton("❌ No",  callback_data=no_data),
    ]])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🗑️ Cancel", callback_data="cancel")
    ]])
