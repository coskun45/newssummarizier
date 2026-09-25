"""
APScheduler-based periodic feed processing.
Runs all active RSS feeds every `feed_refresh_interval` seconds (Ayarlar setting, hourly by default).
"""
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
JOB_ID = "process_all_feeds"


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


def _stored_refresh_interval() -> int:
    from app.db import database
    from app.db import crud

    db = database.SessionLocal()
    try:
        return crud.get_feed_refresh_interval(db)
    finally:
        db.close()


def start_scheduler() -> None:
    """Create and start the background scheduler."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler is already running.")
        return

    interval = _stored_refresh_interval()
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _process_all_feeds,
        trigger=IntervalTrigger(seconds=interval),
        id=JOB_ID,
        name="Periodic RSS feed processing",
        replace_existing=True,
        misfire_grace_time=300,  # tolerate up to 5-min delay
        max_instances=1,  # a slow run is skipped over, never stacked
    )

    _scheduler.start()
    logger.info(f"Scheduler started — feeds will be processed every {interval} seconds.")


def reschedule_feed_processing(interval_seconds: int) -> None:
    """Apply a new refresh interval (saved in Ayarlar) to the running scheduler."""
    if _scheduler is None or not _scheduler.running:
        return
    _scheduler.reschedule_job(JOB_ID, trigger=IntervalTrigger(seconds=interval_seconds))
    logger.info(f"Scheduler: feed refresh interval set to {interval_seconds} seconds.")


def stop_scheduler() -> None:
    """Stop the background scheduler gracefully."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped.")
