"""
APScheduler — uses MemoryJobStore for reliability (no DB dependency).
Scheduled jobs are held in memory; on restart, the Telegram bot
will notify users their scheduled post fired or prompt to reschedule.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from config import IST

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores  = {"default": MemoryJobStore()}
        executors  = {"default": AsyncIOExecutor()}
        _scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            timezone=IST,
        )
    return _scheduler


def start_scheduler() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("✅ Scheduler started (IST timezone, MemoryJobStore)")


def schedule_post(context, run_time: datetime) -> str:
    """
    Schedule a job that executes the pending post at run_time (IST-aware).
    Returns the job ID.
    """
    from bot.handlers import _execute_posting, _format_results  # lazy import

    sched    = get_scheduler()
    job_id   = f"post_{run_time.strftime('%Y%m%d_%H%M%S')}"
    snapshot = dict(context.user_data)

    class _FakeContext:
        user_data = snapshot

    async def _run_scheduled():
        logger.info(f"Running scheduled post: {job_id}")
        try:
            results = await _execute_posting(_FakeContext())
            from telegram import Bot
            from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
            bot = Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=f"⏰ *Scheduled post published!*\n\n{_format_results(results)}",
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Scheduled post failed: {e}")

    sched.add_job(
        _run_scheduled,
        trigger="date",
        run_date=run_time,
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,
    )
    logger.info(f"✅ Post scheduled: {job_id} at {run_time}")
    return job_id
