"""
RSS Feed endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, HttpUrl
from app.db.database import get_db
from app.db import crud
from datetime import datetime

router = APIRouter()


class FeedCreate(BaseModel):
    """Feed creation request."""
    url: HttpUrl
    title: Optional[str] = None
    description: Optional[str] = None


class FeedResponse(BaseModel):
    """Feed response model."""
    id: int
    url: str
    title: Optional[str] = None
    description: Optional[str] = None
    last_fetched: Optional[datetime] = None
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.post("/", response_model=FeedResponse)
async def create_feed(feed: FeedCreate, db: Session = Depends(get_db)):
    """
    Create a new RSS feed.
    """
    # Check if feed already exists
    existing_feed = crud.get_feed_by_url(db, str(feed.url))
    if existing_feed:
        raise HTTPException(status_code=400, detail="Feed already exists")
    
    # Create feed
    db_feed = crud.create_feed(
        db=db,
        url=str(feed.url),
        title=feed.title,
        description=feed.description
    )
    
    return db_feed


@router.get("/", response_model=List[FeedResponse])
async def list_feeds(active_only: bool = True, db: Session = Depends(get_db)):
    """
    List all RSS feeds.
    """
    feeds = crud.get_feeds(db, active_only=active_only)
    return feeds


@router.get("/{feed_id}", response_model=FeedResponse)
async def get_feed(feed_id: int, db: Session = Depends(get_db)):
    """
    Get a specific feed by ID.
    """
    feed = crud.get_feed(db, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    return feed


@router.get("/{feed_id}/check-new")
async def check_new_articles(feed_id: int, db: Session = Depends(get_db)):
    """
    Check how many new articles are available without processing them.
    """
    feed = crud.get_feed(db, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    try:
        # Import here to avoid circular dependency
        from app.agents.tools import fetch_rss_feed
        
        # Fetch RSS feed
        articles = await fetch_rss_feed(feed.url)
        
        # Check which articles are new
        new_count = 0
        new_articles_info = []
        for article in articles:
            existing = crud.get_article_by_url(db, article["url"])
            if not existing:
                new_count += 1
                new_articles_info.append({
                    "title": article["title"],
                    "url": article["url"],
                    "published_at": article.get("published_at")
                })
        
        return {
            "feed_id": feed_id,
            "total_articles": len(articles),
            "new_articles": new_count,
            "existing_articles": len(articles) - new_count,
            "new_articles_list": new_articles_info[:10]  # Limit to first 10
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check feed: {str(e)}")


@router.post("/{feed_id}/refresh")
async def refresh_feed(
    feed_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Trigger manual feed refresh.
    """
    feed = crud.get_feed(db, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")
    
    # Import here to avoid circular dependency
    from app.tasks.background import process_feed_task
    
    # Add background task
    background_tasks.add_task(process_feed_task, feed_id)
    
    return {"status": "queued", "feed_id": feed_id}


@router.delete("/{feed_id}")
async def delete_feed(feed_id: int, db: Session = Depends(get_db)):
    """
    Delete a feed.
    """
    success = crud.delete_feed(db, feed_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"status": "deleted", "feed_id": feed_id}
