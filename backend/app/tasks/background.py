"""
Background tasks for feed processing.
"""
import asyncio
import logging
from typing import Dict, Any, List
from app.agents.graph import get_workflow
from app.db.database import SessionLocal
from app.db import crud

logger = logging.getLogger(__name__)

# In-memory job status tracker: feed_id -> status dict
_job_status: Dict[int, Dict[str, Any]] = {}


def get_job_status(feed_id: int) -> Dict[str, Any]:
    """Return the latest job status for a feed."""
    return _job_status.get(feed_id, {"status": "idle"})


async def process_feed_async(feed_id: int):
    """
    Process a feed asynchronously using LangGraph workflow.
    
    Args:
        feed_id: ID of the feed to process
    """
    db = SessionLocal()
    try:
        # Get feed
        feed = crud.get_feed(db, feed_id)
        if not feed:
            logger.error(f"Feed not found: {feed_id}")
            _job_status[feed_id] = {"status": "error", "message": "Feed not found"}
            return

        # Count articles before processing to detect new ones
        from app.db.models import Article
        from sqlalchemy import func
        articles_before = db.query(func.count(Article.id)).scalar() or 0

        _job_status[feed_id] = {"status": "running"}

        logger.info(f"Starting feed processing: {feed.url}")
        
        # Update last fetched time
        crud.update_feed_last_fetched(db, feed_id)
        
        # Get workflow
        workflow = get_workflow()
        
        # Create initial state
        initial_state = {
            "feed_id": feed_id,
            "feed_url": feed.url,
            "rss_articles": [],
            "current_article_index": 0,
            "processed_articles": [],
            "errors": [],
            "total_articles": 0,
            "total_cost": 0.0,
            "should_continue": True
        }
        
        # Run workflow
        logger.info("Invoking LangGraph workflow...")
        
        from app.core.config import settings
        final_state = await workflow.ainvoke(
            initial_state,
            config={"recursion_limit": settings.graph_recursion_limit}
        )
        
        # Log results
        total_articles = len(final_state.get("processed_articles", []))
        total_cost = final_state.get("total_cost", 0.0)
        errors = final_state.get("errors", [])
        
        # Count new articles added during this run
        db2 = SessionLocal()
        try:
            articles_after = db2.query(func.count(Article.id)).scalar() or 0
        finally:
            db2.close()
        new_articles = max(0, articles_after - articles_before)

        _job_status[feed_id] = {
            "status": "done",
            "new_articles": new_articles,
            "processed": total_articles,
            "errors": len(errors),
        }

        logger.info(
            f"Feed processing completed. "
            f"Articles processed: {total_articles}, "
            f"New: {new_articles}, "
            f"Cost: ${total_cost:.4f}, "
            f"Errors: {len(errors)}"
        )
        
        if errors:
            for error in errors:
                logger.error(f"Processing error: {error}")
        
    except Exception as e:
        logger.error(f"Feed processing failed: {e}", exc_info=True)
        _job_status[feed_id] = {"status": "error", "message": str(e)}
    finally:
        db.close()


async def process_feed_task(feed_id: int):
    """
    Async wrapper for background task.
    
    Args:
        feed_id: ID of the feed to process
    """
    try:
        await process_feed_async(feed_id)
    except Exception as e:
        logger.error(f"Background task failed: {e}", exc_info=True)


# ==================== Article re-processing ("Error" group) ====================

# Global progress of the user-triggered re-process job (the UI polls this).
_reprocess_status: Dict[str, Any] = {"status": "idle", "total": 0, "done": 0, "failed": 0}
# Serializes runs so overlapping requests queue up instead of hammering OpenAI in parallel.
_reprocess_lock = asyncio.Lock()


def get_reprocess_status() -> Dict[str, Any]:
    """Return a copy of the latest re-process job status."""
    return dict(_reprocess_status)


def register_reprocess(count: int) -> None:
    """Account for `count` newly queued articles. Starts a fresh run when idle/finished,
    otherwise extends the run that is already in progress."""
    if _reprocess_status["status"] != "running":
        _reprocess_status.update({"status": "running", "total": 0, "done": 0, "failed": 0})
    _reprocess_status["total"] += count


async def reprocess_articles_task(article_ids: List[int]):
    """Re-run classification + summarization for the given articles, one after another.

    Never raises: a failing article is counted and left as `status="failed"` (still an
    "Error" article) and the run moves on to the next one.
    """
    from app.services.summary_service import process_article_by_id

    def _mark_failed(article_id: int) -> None:
        # The route set the article to "pending"; put it back into the "Error" group.
        db = SessionLocal()
        try:
            crud.update_article_status(db, article_id, "failed")
        finally:
            db.close()

    async with _reprocess_lock:
        remaining = list(article_ids)
        try:
            while remaining:
                article_id = remaining[0]
                try:
                    result = await process_article_by_id(article_id)
                    if not result.get("success"):
                        _reprocess_status["failed"] += 1
                except Exception as e:
                    logger.error(f"Re-processing article {article_id} failed: {e}", exc_info=True)
                    _reprocess_status["failed"] += 1
                    _mark_failed(article_id)
                remaining.pop(0)
                _reprocess_status["done"] += 1
        finally:
            # Cancellation/shutdown mid-run: don't strand the rest as "pending" (invisible to
            # the Error tab) and don't leave the status stuck on "running" (UI polls forever).
            for article_id in remaining:
                _mark_failed(article_id)
                _reprocess_status["failed"] += 1
                _reprocess_status["done"] += 1
            if _reprocess_status["done"] >= _reprocess_status["total"]:
                _reprocess_status["status"] = "done"
