"""
APScheduler-based periodic feed processing.
Runs all active RSS feeds once every hour.
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _process_all_feeds() -> None:
    """Fetch and process all active RSS feeds."""
    from app.db.database import SessionLocal
    from app.db import crud
    from app.tasks.background import process_feed_task

    # Read the ids and let the session go: the run lasts for many minutes and each feed
    # pipeline opens its own sessions.
    db = SessionLocal()
    try:
        feed_ids = [feed.id for feed in crud.get_feeds(db, active_only=True)]
    finally:
        db.close()

    if not feed_ids:
        logger.info("Scheduler: no active feeds found.")
        return

    logger.info(f"Scheduler: starting processing for {len(feed_ids)} active feed(s).")
    for feed_id in feed_ids:
        try:
            await process_feed_task(feed_id)
        except Exception as exc:
            logger.error(f"Scheduler: error processing feed {feed_id}: {exc}", exc_info=True)

    logger.info("Scheduler: all feeds processed.")


def start_scheduler() -> None:
    """Create and start the background scheduler."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler is already running.")
        return

    _scheduler = AsyncIOScheduler()

    # Run at the top of every hour  (minute=0)
    _scheduler.add_job(
        _process_all_feeds,
        trigger=CronTrigger(minute=0),
        id="process_all_feeds",
        name="Hourly RSS feed processing",
        replace_existing=True,
        misfire_grace_time=300,  # tolerate up to 5-min delay
    )

    _scheduler.start()
    logger.info("Scheduler started — feeds will be processed at the top of every hour.")


def stop_scheduler() -> None:
    """Stop the background scheduler gracefully."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
