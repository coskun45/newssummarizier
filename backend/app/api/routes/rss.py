"""
RSS Feed endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel, HttpUrl
from app.db.database import get_db
from app.db import crud, models
from app.api.deps import require_admin
from app.core.url_safety import assert_safe_feed_url
from datetime import datetime

router = APIRouter()


class FeedCreate(BaseModel):
    """Feed creation request."""
    url: HttpUrl
    title: Optional[str] = None
    description: Optional[str] = None


class FeedUpdate(BaseModel):
    """Feed update request. All fields optional — only provided ones are changed."""
    url: Optional[HttpUrl] = None
    title: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


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
async def create_feed(
    feed: FeedCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Create a new RSS feed (admin only).
    """
    assert_safe_feed_url(str(feed.url))

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



@router.put("/{feed_id}", response_model=FeedResponse)
async def update_feed(
    feed_id: int,
    feed_update: FeedUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Update an existing RSS feed (URL, title, description, active state). Admin only.
    """
    feed = crud.get_feed(db, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail="Feed not found")

    new_url = str(feed_update.url) if feed_update.url is not None else None

    # Reject a URL change that collides with a different existing feed
    if new_url and new_url != feed.url:
        assert_safe_feed_url(new_url)
        existing = crud.get_feed_by_url(db, new_url)
        if existing and existing.id != feed_id:
            raise HTTPException(status_code=400, detail="Feed already exists")

    updated = crud.update_feed(
        db,
        feed_id=feed_id,
        url=new_url,
        title=feed_update.title,
        description=feed_update.description,
        is_active=feed_update.is_active,
    )
    return updated


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


@router.get("/{feed_id}/refresh-status")
async def get_refresh_status(feed_id: int):
    """
    Get the current processing status for a feed refresh job.
    Returns: {status: 'idle'|'running'|'done'|'error', new_articles?, processed?, errors?, message?}
    """
    from app.tasks.background import get_job_status
    return get_job_status(feed_id)


@router.delete("/{feed_id}")
async def delete_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Delete a feed (admin only).
    """
    success = crud.delete_feed(db, feed_id)
    if not success:
        raise HTTPException(status_code=404, detail="Feed not found")
    return {"status": "deleted", "feed_id": feed_id}
