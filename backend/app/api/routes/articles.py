"""
Article endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.db.database import get_db
from app.db import crud, models


router = APIRouter()

@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    """
    Delete an article by ID.
    """
    article = crud.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    db.delete(article)
    db.commit()
    return None


class TopicInfo(BaseModel):
    """Topic information."""
    id: int
    name: str
    color: Optional[str] = None
    confidence: Optional[float] = None


class ArticleResponse(BaseModel):
    """Article response model."""
    id: int
    url: str
    title: str
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime
    status: str
    importance: Optional[str] = None
    priority: Optional[str] = None
    topics: List[TopicInfo] = []
    has_summaries: bool = False
    is_read: bool = False

    class Config:
        from_attributes = True


class ArticleDetailResponse(ArticleResponse):
    """Detailed article response with content."""
    raw_content: Optional[str] = None
    cleaned_content: Optional[str] = None


class ArticleListResponse(BaseModel):
    """Paginated article list response."""
    articles: List[ArticleResponse]
    total: int
    skip: int
    limit: int


@router.get("/", response_model=ArticleListResponse)
async def list_articles(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    topic_ids: Optional[str] = Query(None, description="Comma-separated topic IDs"),
    search: Optional[str] = None,
    status: Optional[str] = None,
    feed_id: Optional[int] = Query(None),
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs"),
    priority: Optional[str] = Query(None, description="Filter by priority: high, med, low"),
    published_from: Optional[datetime] = Query(None, description="Published date from (ISO 8601)"),
    published_to: Optional[datetime] = Query(None, description="Published date to (ISO 8601)"),
    fetched_from: Optional[datetime] = Query(None, description="Fetched date from (ISO 8601)"),
    fetched_to: Optional[datetime] = Query(None, description="Fetched date to (ISO 8601)"),
    is_read: Optional[bool] = Query(None, description="Filter by read status: true=read, false=unread"),
    db: Session = Depends(get_db)
):
    """
    List articles with optional filtering.
    """
    # Parse topic IDs
    topic_id_list = None
    if topic_ids:
        try:
            topic_id_list = [int(tid) for tid in topic_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid topic IDs format")

    # Parse feed IDs
    feed_id_list = None
    if feed_ids:
        try:
            feed_id_list = [int(fid) for fid in feed_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid feed IDs format")

    # Get articles
    articles = crud.get_articles(
        db=db,
        skip=skip,
        limit=limit,
        topic_ids=topic_id_list,
        search_query=search,
        status=status,
        feed_id=feed_id,
        feed_ids=feed_id_list,
        priority=priority,
        start_date=published_from,
        end_date=published_to,
        fetched_from=fetched_from,
        fetched_to=fetched_to,
        is_read=is_read,
    )

    # Get total count
    total = crud.count_articles(
        db=db,
        topic_ids=topic_id_list,
        search_query=search,
        status=status,
        feed_id=feed_id,
        feed_ids=feed_id_list,
        priority=priority,
        start_date=published_from,
        end_date=published_to,
        fetched_from=fetched_from,
        fetched_to=fetched_to,
        is_read=is_read,
    )
    
    # Transform to response model
    articles_response = []
    for article in articles:
        article_data = {
            "id": article.id,
            "url": article.url,
            "title": article.title,
            "author": article.author,
            "published_at": article.published_at,
            "fetched_at": article.fetched_at,
            "status": article.status,
            "importance": article.importance,
            "priority": article.priority,
            "topics": [
                {
                    "id": at.topic.id,
                    "name": at.topic.name,
                    "color": at.topic.color,
                    "confidence": at.confidence
                }
                for at in article.topics
            ],
            "has_summaries": len(article.summaries) > 0,
            "is_read": article.is_read,
        }
        articles_response.append(ArticleResponse(**article_data))
    
    return ArticleListResponse(
        articles=articles_response,
        total=total,
        skip=skip,
        limit=limit
    )


@router.patch("/{article_id}/read")
async def mark_article_read(
    article_id: int,
    db: Session = Depends(get_db)
):
    """
    Mark an article as read by the user.
    """
    article = crud.mark_article_read(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article_id, "is_read": True}


class BulkReadRequest(BaseModel):
    """Request body for bulk mark-as-read."""
    article_ids: Optional[List[int]] = None
    mark_all: bool = False


@router.post("/mark-read-bulk")
async def mark_articles_read_bulk(
    body: BulkReadRequest,
    db: Session = Depends(get_db)
):
    """
    Mark multiple articles as read. Provide article_ids for specific articles,
    or set mark_all=true to mark all unread articles.
    """
    if not body.mark_all and not body.article_ids:
        raise HTTPException(status_code=400, detail="Provide article_ids or set mark_all=true")
    ids = None if body.mark_all else body.article_ids
    count = crud.mark_articles_read_bulk(db, ids)
    return {"marked_count": count}


@router.get("/counts")
async def get_article_counts(db: Session = Depends(get_db)):
    """Get article counts grouped by priority and feed."""
    from sqlalchemy import func
    priority_rows = db.query(
        models.Article.priority,
        func.count(models.Article.id)
    ).filter(models.Article.priority.isnot(None)).group_by(models.Article.priority).all()

    feed_rows = db.query(
        models.Article.feed_id,
        func.count(models.Article.id)
    ).group_by(models.Article.feed_id).all()

    unimportant_count = db.query(func.count(models.Article.id)).filter(
        models.Article.importance == "unimportant"
    ).scalar() or 0

    unread_count = db.query(func.count(models.Article.id)).filter(
        models.Article.is_read.is_(False)
    ).scalar() or 0

    read_count = db.query(func.count(models.Article.id)).filter(
        models.Article.is_read.is_(True)
    ).scalar() or 0

    return {
        "by_priority": {p: c for p, c in priority_rows},
        "by_feed": {str(f): c for f, c in feed_rows},
        "unimportant_count": unimportant_count,
        "unread_count": unread_count,
        "read_count": read_count,
    }


@router.get("/{article_id}", response_model=ArticleDetailResponse)
async def get_article(article_id: int, db: Session = Depends(get_db)):
    """
    Get detailed article information.
    """
    article = crud.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    article_data = {
        "id": article.id,
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "published_at": article.published_at,
        "fetched_at": article.fetched_at,
        "raw_content": article.raw_content,
        "cleaned_content": article.cleaned_content,
        "status": article.status,
        "importance": article.importance,
        "priority": article.priority,
        "topics": [
            {
                "id": at.topic.id,
                "name": at.topic.name,
                "color": at.topic.color,
                "confidence": at.confidence
            }
            for at in article.topics
        ],
        "has_summaries": len(article.summaries) > 0,
        "is_read": article.is_read,
    }
    
    return ArticleDetailResponse(**article_data)


@router.get("/topic/{topic_name}")
async def get_articles_by_topic(
    topic_name: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db)
):
    """
    Get articles by topic name.
    """
    # Get topic
    topic = crud.get_topic_by_name(db, topic_name)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    
    # Get articles
    articles = crud.get_articles(
        db=db,
        skip=skip,
        limit=limit,
        topic_ids=[topic.id]
    )
    
    total = crud.count_articles(db=db, topic_ids=[topic.id])
    
    articles_response = []
    for article in articles:
        article_data = {
            "id": article.id,
            "url": article.url,
            "title": article.title,
            "author": article.author,
            "published_at": article.published_at,
            "fetched_at": article.fetched_at,
            "status": article.status,
            "importance": article.importance,
            "priority": article.priority,
            "topics": [
                {
                    "id": at.topic.id,
                    "name": at.topic.name,
                    "color": at.topic.color,
                    "confidence": at.confidence
                }
                for at in article.topics
            ],
            "has_summaries": len(article.summaries) > 0,
            "is_read": article.is_read,
        }
        articles_response.append(ArticleResponse(**article_data))
    
    return ArticleListResponse(
        articles=articles_response,
        total=total,
        skip=skip,
        limit=limit
    )
