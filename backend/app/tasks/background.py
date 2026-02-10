"""
Background tasks for feed processing.
"""
import logging
from app.agents.graph import get_workflow
from app.db.database import SessionLocal
from app.db import crud
from datetime import datetime

logger = logging.getLogger(__name__)


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
            return
        
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
        
        final_state = await workflow.ainvoke(initial_state)
        
        # Log results
        total_articles = len(final_state.get("processed_articles", []))
        total_cost = final_state.get("total_cost", 0.0)
        errors = final_state.get("errors", [])
        
        logger.info(
            f"Feed processing completed. "
            f"Articles processed: {total_articles}, "
            f"Cost: ${total_cost:.4f}, "
            f"Errors: {len(errors)}"
        )
        
        if errors:
            for error in errors:
                logger.error(f"Processing error: {error}")
        
    except Exception as e:
        logger.error(f"Feed processing failed: {e}", exc_info=True)
    finally:
        db.close()


async def process_feed_task(feed_id: int):
    """
    Async wrapper for background task.
    
    Args:
        feed_id: ID of the feed to process
    """
    try:
        # Run async function directly (no asyncio.run needed)
        await process_feed_async(feed_id)
    except Exception as e:
        logger.error(f"Background task failed: {e}", exc_info=True)
