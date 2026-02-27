"""
Post memory module — fetches recent post context from Neon DB
to allow Gemini to generate connected, relatable post chains.
"""
import logging
from database.models import get_recent_context, get_recent_posts

logger = logging.getLogger(__name__)


async def build_context_string(limit: int = 3) -> str:
    """
    Returns a plain-text summary of recent posts for the content agent.
    Used to make each post a natural continuation of the previous one.
    """
    try:
        contexts = await get_recent_context(limit)
        if not contexts:
            return ""

        lines = ["Recent posts by Abeer (for narrative continuity):"]
        for i, ctx in enumerate(contexts, 1):
            platforms = ", ".join(ctx.get("platforms", []))
            lines.append(
                f"{i}. [{platforms}] Topic: {ctx['topic']}\n"
                f"   Summary: {ctx['summary']}"
            )
        return "\n".join(lines)

    except Exception as e:
        logger.warning(f"Failed to fetch post context: {e}")
        return ""


async def get_last_post_topic() -> str | None:
    """Returns the topic of the most recent post, or None."""
    try:
        posts = await get_recent_posts(limit=1)
        return posts[0]["topic"] if posts else None
    except Exception:
        return None


async def format_history_message(limit: int = 5) -> str:
    """Formats recent post history for the /history command."""
    try:
        posts = await get_recent_posts(limit)
        if not posts:
            return "📭 No posts yet. Use /post to create your first one!"

        lines = ["📋 *Recent Posts*\n"]
        for i, p in enumerate(posts, 1):
            platforms = ", ".join(p.get("platforms") or [])
            date_str  = p["posted_at"].strftime("%d %b %Y %H:%M") if p.get("posted_at") else "—"
            topic     = p["topic"][:60] + "…" if len(p["topic"]) > 60 else p["topic"]
            lines.append(f"{i}. *{topic}*\n   🕐 {date_str} | 📡 {platforms}")

            # Append available links
            links = []
            if p.get("linkedin_url"): links.append(f"[LinkedIn]({p['linkedin_url']})")
            if p.get("medium_url"):   links.append(f"[Medium]({p['medium_url']})")
            if p.get("github_url"):   links.append(f"[GitHub]({p['github_url']})")
            if links:
                lines.append("   " + " · ".join(links))
            lines.append("")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"History fetch failed: {e}")
        return "⚠️ Could not fetch post history."
