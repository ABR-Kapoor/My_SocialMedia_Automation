"""
Main entry point — starts the Telegram bot + Flask OAuth server + APScheduler.
Always-running service for Render.com deployment.
"""
import asyncio
import logging
import threading
import sys
from telegram.ext import Application
from config import TELEGRAM_BOT_TOKEN
from bot.handlers import register_all_handlers
from auth.oauth_server import run_flask_server
from scheduler.post_scheduler import start_scheduler
from database.connection import run_migrations, close_pool

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


async def startup(app):
    """Run async startup tasks before the bot begins polling."""
    logger.info("🔧 Running database migrations…")
    await run_migrations()

    # Register commands so they appear in Telegram's / menu
    from telegram import BotCommand
    commands = [
        BotCommand("start",         "👋 Welcome & help"),
        BotCommand("post",          "✍️ Create & publish a post"),
        BotCommand("github_commit", "🐙 Check & auto-commit to DSA-java"),
        BotCommand("auth_linkedin", "🔷 LinkedIn connection status"),
        BotCommand("history",       "📋 Recent post history"),
        BotCommand("style",         "🎨 Update your writing style"),
    ]
    await app.bot.set_my_commands(commands)
    logger.info("✅ Bot commands registered in Telegram menu")
    logger.info("✅ Startup complete")


async def shutdown():
    """Clean shutdown."""
    await close_pool()
    logger.info("Database pool closed")


def main():
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("  Abeer Brand Bot — Starting Up")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # 1️⃣  Start Flask OAuth server in background thread
    flask_thread = threading.Thread(target=run_flask_server, daemon=True, name="FlaskOAuth")
    flask_thread.start()
    logger.info("✅ Flask OAuth server started in background thread")

    # 2️⃣  Build the Telegram Application
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(startup)
        .post_shutdown(lambda _: shutdown())
        .build()
    )

    # 3️⃣  Register all bot handlers
    register_all_handlers(app)

    # 4️⃣  Start APScheduler
    start_scheduler()

    # 5️⃣  Run the bot (blocking poll)
    logger.info("✅ Bot is polling… Send /start in Telegram")
    app.run_polling(
        allowed_updates=["message", "callback_query"],
        drop_pending_updates=True,
        stop_signals=(),          # Windows: signals not supported in non-main thread
    )


if __name__ == "__main__":
    main()
