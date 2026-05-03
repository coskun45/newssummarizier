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

    db = SessionLocal()
    try:
        feeds = crud.get_feeds(db, active_only=True)
        if not feeds:
            logger.info("Scheduler: no active feeds found.")
            return

        logger.info(f"Scheduler: starting processing for {len(feeds)} active feed(s).")
        for feed in feeds:
            try:
                await process_feed_task(feed.id)
            except Exception as exc:
                logger.error(f"Scheduler: error processing feed {feed.id}: {exc}", exc_info=True)

        logger.info("Scheduler: all feeds processed.")
    finally:
        db.close()


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
