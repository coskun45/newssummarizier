"""
Agent node functions for the news processing workflow.
"""
import logging
from typing import Any, Dict
from app.agents.state import NewsProcessingState, ArticleData
from app.agents.tools import fetch_rss_feed, extract_article_content, truncate_content
from app.services.summary_service import (
    categorize_article_topics,
    generate_summary
)
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
        
        # Filter out articles that already exist in database
        db = SessionLocal()
        try:
            new_articles = []
            for article in articles:
                existing = crud.get_article_by_url(db, article["url"])
                if not existing:
                    article["status"] = "pending"
                    new_articles.append(article)
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


async def article_processor_node(state: NewsProcessingState) -> Dict[str, Any]:
    """
    Process individual article: scrape, categorize, and summarize.
    """
    articles = state.get("rss_articles", [])
    index = state.get("current_article_index", 0)
    
    if index >= len(articles):
        logger.info("All articles processed")
        return {
            "should_continue": False
        }
    
    article = articles[index]
    logger.info(f"Processing article {index + 1}/{len(articles)}: {article['title']}")
    
    db = SessionLocal()
    db_article = None
    
    try:
        # Step 1: Create article in database
        db_article = crud.create_article(
            db=db,
            feed_id=state["feed_id"],
            url=article["url"],
            title=article["title"],
            author=article.get("author"),
            published_at=article.get("published_at"),
            raw_content=article.get("raw_content")
        )
        
        crud.create_log(
            db=db,
            article_id=db_article.id,
            agent_name="article_processor",
            status="started",
            message="Article processing started"
        )
        
        # Step 2: Extract content from web page
        try:
            cleaned_content = await extract_article_content(article["url"])
            
            if cleaned_content:
                article["cleaned_content"] = cleaned_content
                crud.update_article_content(
                    db=db,
                    article_id=db_article.id,
                    cleaned_content=cleaned_content
                )
                crud.update_article_status(db=db, article_id=db_article.id, status="scraped")
                crud.create_log(
                    db=db,
                    article_id=db_article.id,
                    agent_name="web_scraper",
                    status="success",
                    message=f"Extracted {len(cleaned_content)} characters"
                )
            else:
                # Fallback to RSS content
                article["cleaned_content"] = article.get("raw_content", "")
                crud.create_log(
                    db=db,
                    article_id=db_article.id,
                    agent_name="web_scraper",
                    status="skipped",
                    message="Using RSS content as fallback"
                )
        except Exception as e:
            logger.warning(f"Content extraction failed, using RSS content: {e}")
            article["cleaned_content"] = article.get("raw_content", "")
            crud.create_log(
                db=db,
                article_id=db_article.id,
                agent_name="web_scraper",
                status="error",
                message="Failed to extract content, using RSS fallback",
                error_details=str(e)
            )
        
        # Step 3: Categorize by topics
        try:
            # Get enabled topics from settings
            enabled_topics_setting = crud.get_setting(db, "enabled_topics") or ""
            enabled_topic_ids = []
            if enabled_topics_setting:
                try:
                    enabled_topic_ids = [int(x.strip()) for x in enabled_topics_setting.split(",") if x.strip()]
                except:
                    enabled_topic_ids = []
            
            content_for_categorization = article.get("cleaned_content") or article.get("raw_content", "")
            topics = await categorize_article_topics(
                title=article["title"],
                content=truncate_content(content_for_categorization, 2000)
            )
            
            article["topics"] = topics
            
            # Save topics to database (filter by enabled topics if set)
            for topic in topics:
                topic_db = crud.get_topic_by_name(db, topic["name"])
                if topic_db:
                    # Only add if topic is enabled (or all topics enabled if empty)
                    if not enabled_topic_ids or topic_db.id in enabled_topic_ids:
                        crud.add_article_topic(
                            db=db,
                            article_id=db_article.id,
                            topic_id=topic_db.id,
                            confidence=topic.get("confidence", 1.0)
                        )
            
            crud.create_log(
                db=db,
                article_id=db_article.id,
                agent_name="topic_categorizer",
                status="success",
                message=f"Categorized into {len(topics)} topics"
            )
        except Exception as e:
            logger.error(f"Topic categorization failed: {e}")
            article["topics"] = []
            crud.create_log(
                db=db,
                article_id=db_article.id,
                agent_name="topic_categorizer",
                status="error",
                message="Failed to categorize topics",
                error_details=str(e)
            )
        
        # Step 4: Generate summaries based on user settings
        total_cost = 0.0
        content_for_summary = article.get("cleaned_content") or article.get("raw_content", "")
        
        if content_for_summary:
            # Get enabled summary types from settings
            enabled_summary_types = crud.get_setting(db, "enabled_summary_types") or "brief,standard,detailed"
            enabled_types = [x.strip() for x in enabled_summary_types.split(",") if x.strip()]
            
            summary_types_map = {
                "brief": ("brief", "brief"),
                "standard": ("standard", "standard"),
                "detailed": ("detailed", "detailed")
            }
            
            # Only generate enabled summary types
            summary_types = [summary_types_map[st] for st in enabled_types if st in summary_types_map]
            
            for summary_type, article_key in summary_types:
                try:
                    summary_result = await generate_summary(
                        title=article["title"],
                        content=truncate_content(content_for_summary),
                        summary_type=summary_type
                    )
                    
                    article[f"summary_{article_key}"] = summary_result["summary_text"]
                    total_cost += summary_result["cost"]
                    
                    # Save summary to database
                    crud.create_summary(
                        db=db,
                        article_id=db_article.id,
                        summary_text=summary_result["summary_text"],
                        summary_type=summary_type,
                        model_used=summary_result["model_used"],
                        tokens_used=summary_result["tokens_used"],
                        cost=summary_result["cost"]
                    )
                    
                except Exception as e:
                    logger.error(f"Summary generation failed for {summary_type}: {e}")
                    article[f"summary_{article_key}"] = None
                    crud.create_log(
                        db=db,
                        article_id=db_article.id,
                        agent_name="summarizer",
                        status="error",
                        message=f"Failed to generate {summary_type} summary",
                        error_details=str(e)
                    )
        
        # Update article status to summarized
        crud.update_article_status(db=db, article_id=db_article.id, status="summarized")
        crud.create_log(
            db=db,
            article_id=db_article.id,
            agent_name="article_processor",
            status="success",
            message=f"Article processing completed. Cost: ${total_cost:.4f}"
        )
        
        article["status"] = "summarized"
        
        # Update state
        processed = state.get("processed_articles", [])
        processed.append(article)
        
        return {
            "current_article_index": index + 1,
            "processed_articles": processed,
            "total_cost": state.get("total_cost", 0.0) + total_cost,
            "should_continue": index + 1 < len(articles)
        }
        
    except Exception as e:
        logger.error(f"Article processing failed: {e}")
        
        if db_article:
            crud.update_article_status(db=db, article_id=db_article.id, status="failed")
            crud.create_log(
                db=db,
                article_id=db_article.id,
                agent_name="article_processor",
                status="error",
                message="Article processing failed",
                error_details=str(e)
            )
        
        errors = state.get("errors", [])
        errors.append({
            "node": "article_processor",
            "article_url": article.get("url"),
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Continue to next article despite error
        return {
            "current_article_index": index + 1,
            "errors": errors,
            "should_continue": index + 1 < len(articles)
        }
    finally:
        db.close()


def should_continue_processing(state: NewsProcessingState) -> str:
    """
    Decide whether to continue processing articles.
    """
    if state.get("should_continue", False):
        return "continue"
    return "end"
