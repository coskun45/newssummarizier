"""
Agent node functions for the news processing workflow.
"""
import logging
from typing import Any, Dict
from app.agents.state import NewsProcessingState
from app.agents.tools import fetch_rss_feed
from app.services.summary_service import process_article
from app.db.database import SessionLocal
from app.db import crud
from datetime import datetime

logger = logging.getLogger(__name__)


async def rss_fetcher_node(state: NewsProcessingState) -> Dict[str, Any]:
    """
    Fetch articles from RSS feed.
    """
    logger.info(f"RSS Fetcher Node - Processing feed: {state['feed_url']}")
    
    try:
        # Fetch RSS feed
        articles = await fetch_rss_feed(state["feed_url"])
        
        # Filter out articles that already exist in database, or that the
        # user explicitly deleted before (tombstoned) — otherwise a feed that
        # still lists an old item keeps recreating it on every refresh.
        db = SessionLocal()
        try:
            deleted_urls = crud.get_deleted_urls(db)
            seen_urls = set()
            new_articles = []
            for article in articles:
                if article["url"] in deleted_urls:
                    logger.info(f"Article was deleted by user, skipping: {article['url']}")
                    continue
                if article["url"] in seen_urls:
                    # Some feeds (e.g. multi-category aggregates) list the same
                    # URL more than once in a single poll. Only the DB is
                    # checked below, so a same-batch duplicate would otherwise
                    # pass that check twice and crash article_processor_node
                    # on the unique constraint when the second copy is inserted.
                    logger.info(f"Duplicate URL within this feed poll, skipping: {article['url']}")
                    continue
                existing = crud.get_article_by_url(db, article["url"])
                if not existing:
                    article["status"] = "pending"
                    new_articles.append(article)
                    seen_urls.add(article["url"])
                else:
                    logger.info(f"Article already exists: {article['url']}")
            
            logger.info(f"Found {len(new_articles)} new articles out of {len(articles)} total")
            
            return {
                "rss_articles": new_articles,
                "total_articles": len(new_articles),
                "current_article_index": 0,
                "processed_articles": [],
                "errors": state.get("errors", []),
                "total_cost": 0.0,
                "should_continue": len(new_articles) > 0
            }
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"RSS Fetcher Node failed: {e}")
        errors = state.get("errors", [])
        errors.append({
            "node": "rss_fetcher",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })
        return {
            "rss_articles": [],
            "total_articles": 0,
            "errors": errors,
            "should_continue": False
        }


async def _process_new_article(feed_id: int, article: Dict[str, Any]) -> Dict[str, Any]:
    """Store one new RSS entry and run it through the shared processing path
    (`summary_service.process_article`: scrape → classify → summarize).

    Never raises: returns {"url", "title", "status", "created", "cost", "error"} so one bad
    article can't stop the run.
    """
    outcome = {"url": article.get("url"), "title": article.get("title"), "status": "failed",
               "created": False, "cost": 0.0, "error": None}
    db = SessionLocal()
    article_id = None
    try:
        try:
            db_article = crud.create_article(
                db=db,
                feed_id=feed_id,
                url=article["url"],
                title=article["title"],
                author=article.get("author"),
                published_at=article.get("published_at"),
                raw_content=article.get("raw_content"),
                image_url=article.get("image_url")
            )
        except Exception as e:
            # e.g. the same URL was inserted meanwhile by another run — nothing new to process
            db.rollback()
            outcome["error"] = f"Could not store article: {e}"
            return outcome

        article_id = db_article.id
        outcome["created"] = True
        crud.create_log(
            db=db,
            article_id=article_id,
            agent_name="article_processor",
            status="started",
            message="Article processing started"
        )

        result = await process_article(db, article_id)
        outcome["status"] = result["status"]
        outcome["cost"] = result.get("cost", 0.0)
        if not result.get("success"):
            outcome["error"] = f"Article processing ended as {result['status']}"
        return outcome

    except Exception as e:
        logger.error(f"Article processing failed: {e}")
        outcome["error"] = str(e)
        if article_id is not None:
            db.rollback()
            crud.update_article_status(db=db, article_id=article_id, status="failed")
            crud.create_log(
                db=db,
                article_id=article_id,
                agent_name="article_processor",
                status="error",
                message="Article processing failed",
                error_details=str(e)
            )
        return outcome
    finally:
        db.close()


async def article_processor_node(state: NewsProcessingState) -> Dict[str, Any]:
    """
    Process every new article of the feed, one after another, in a single graph step.

    Looping inside the node (instead of one graph step per article) keeps a large refresh from
    hitting LangGraph's recursion limit. Only a small outcome per article is kept in state, not
    its full text.
    """
    articles = state.get("rss_articles", [])
    errors = list(state.get("errors", []))
    processed = list(state.get("processed_articles", []))
    total_cost = state.get("total_cost", 0.0)

    for index, article in enumerate(articles[state.get("current_article_index", 0):]):
        logger.info(f"Processing article {index + 1}/{len(articles)}: {article.get('title')}")
        outcome = await _process_new_article(state["feed_id"], article)
        total_cost += outcome["cost"]
        processed.append(outcome)
        if outcome["error"]:
            errors.append({
                "node": "article_processor",
                "article_url": outcome["url"],
                "error": outcome["error"],
                "timestamp": datetime.utcnow().isoformat()
            })

    return {
        "current_article_index": len(articles),
        "processed_articles": processed,
        "errors": errors,
        "total_cost": total_cost,
        "should_continue": False
    }
