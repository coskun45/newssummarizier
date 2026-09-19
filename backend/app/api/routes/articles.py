"""
Article endpoints.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
from app.db.database import get_db
from app.db import crud, models


router = APIRouter()


def _parse_comma_ids(raw: Optional[str], field_name: str) -> Optional[List[int]]:
    """Parse a comma-separated query/body string of ids into a list of ints."""
    if not raw:
        return None
    try:
        return [int(v) for v in raw.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


VALID_PRIORITIES = {"high", "med", "low"}


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_article(article_id: int, db: Session = Depends(get_db)):
    """
    Delete an article by ID. Its URL is tombstoned so the next feed refresh
    doesn't recreate it if the RSS feed still lists the item.
    """
    if not crud.delete_article(db, article_id):
        raise HTTPException(status_code=404, detail="Article not found")
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
    image_url: Optional[str] = None
    topics: List[TopicInfo] = []
    has_summaries: bool = False
    is_read: bool = False
    is_starred: bool = False

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
    is_starred: Optional[bool] = Query(None, description="Filter by the user-curated 'Önemli' group"),
    is_error: Optional[bool] = Query(None, description="true = only articles without a severity label (\"Error\" group), false = everything except them"),
    db: Session = Depends(get_db)
):
    """
    List articles with optional filtering.
    """
    topic_id_list = _parse_comma_ids(topic_ids, "topic IDs")
    feed_id_list = _parse_comma_ids(feed_ids, "feed IDs")

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
        is_starred=is_starred,
        is_error=is_error,
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
        is_starred=is_starred,
        is_error=is_error,
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
            "image_url": article.image_url,
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
            "is_starred": article.is_starred,
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
    # When mark_all=true, these scope it to the caller's active filters instead
    # of every unread article in the database (mirrors list_articles' filters).
    topic_ids: Optional[str] = None
    search: Optional[str] = None
    status: Optional[str] = None
    feed_id: Optional[int] = None
    feed_ids: Optional[str] = None
    priority: Optional[str] = None
    published_from: Optional[datetime] = None
    published_to: Optional[datetime] = None
    fetched_from: Optional[datetime] = None
    fetched_to: Optional[datetime] = None
    is_starred: Optional[bool] = None
    is_error: Optional[bool] = None


@router.post("/mark-read-bulk")
async def mark_articles_read_bulk(
    body: BulkReadRequest,
    db: Session = Depends(get_db)
):
    """
    Mark multiple articles as read. Provide article_ids for specific articles,
    or set mark_all=true to mark all unread articles matching the given filters
    (no filters = every unread article).
    """
    if not body.mark_all and not body.article_ids:
        raise HTTPException(status_code=400, detail="Provide article_ids or set mark_all=true")
    ids = None if body.mark_all else body.article_ids
    if ids is not None:
        count = crud.mark_articles_read_bulk(db, ids)
    else:
        count = crud.mark_articles_read_bulk(
            db,
            None,
            topic_ids=_parse_comma_ids(body.topic_ids, "topic IDs"),
            search_query=body.search,
            status=body.status,
            feed_id=body.feed_id,
            feed_ids=_parse_comma_ids(body.feed_ids, "feed IDs"),
            priority=body.priority,
            start_date=body.published_from,
            end_date=body.published_to,
            fetched_from=body.fetched_from,
            fetched_to=body.fetched_to,
            is_starred=body.is_starred,
            is_error=body.is_error,
        )
    return {"marked_count": count}


class StarRequest(BaseModel):
    """Request body for toggling an article's 'Önemli' (starred) state."""
    starred: bool = True


@router.patch("/{article_id}/star")
async def star_article(article_id: int, body: StarRequest, db: Session = Depends(get_db)):
    """Add or remove an article from the user-curated 'Önemli' group."""
    article = crud.set_article_starred(db, article_id, body.starred)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article_id, "is_starred": body.starred}


@router.post("/unstar-all")
async def unstar_all_articles(db: Session = Depends(get_db)):
    """Clear the whole 'Önemli' group."""
    count = crud.unstar_all(db)
    return {"unstarred_count": count}


@router.get("/topic/{topic_id}/ids")
async def get_article_ids_by_topic(topic_id: int, db: Session = Depends(get_db)):
    """All article ids tagged with this topic, regardless of status (used for 'select all' by category)."""
    if not crud.get_topic(db, topic_id):
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"article_ids": crud.get_article_ids_by_topic(db, topic_id)}


@router.post("/priority/{priority}/delete-all")
async def delete_articles_by_priority(
    priority: str,
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the delete to"),
    db: Session = Depends(get_db)
):
    """Delete every unread article with this priority, optionally scoped to feed_ids."""
    if priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority; expected one of: high, med, low")
    count = crud.delete_articles_by_priority(db, priority, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"deleted_count": count}


@router.post("/priority/{priority}/archive-all")
async def archive_articles_by_priority(
    priority: str,
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the archive to"),
    db: Session = Depends(get_db)
):
    """Mark every unread article with this priority as read, optionally scoped to feed_ids."""
    if priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority; expected one of: high, med, low")
    count = crud.mark_articles_read_by_priority(db, priority, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"archived_count": count}


@router.post("/unimportant/delete-all")
async def delete_articles_unimportant(
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the delete to"),
    db: Session = Depends(get_db)
):
    """Delete every unread unimportant article, optionally scoped to feed_ids."""
    count = crud.delete_articles_unimportant(db, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"deleted_count": count}


@router.post("/unimportant/archive-all")
async def archive_articles_unimportant(
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the archive to"),
    db: Session = Depends(get_db)
):
    """Mark every unread unimportant article as read, optionally scoped to feed_ids."""
    count = crud.mark_articles_read_unimportant(db, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"archived_count": count}


class ReprocessRequest(BaseModel):
    """Request body for re-running "Error" articles through the workflow."""
    article_ids: Optional[List[int]] = None
    all_errors: bool = False
    # With all_errors=true, optionally scope to these feeds.
    feed_ids: Optional[List[int]] = None


@router.post("/reprocess")
async def reprocess_articles(
    body: ReprocessRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """
    Re-run classification + summarization for "Error" articles (no severity label).
    Provide article_ids for specific articles, or all_errors=true for every Error article
    (optionally scoped to feed_ids). Ids that aren't in the Error group are ignored.
    Runs in the background — poll GET /reprocess-status for progress.
    """
    if not body.all_errors and not body.article_ids:
        raise HTTPException(status_code=400, detail="Provide article_ids or set all_errors=true")
    ids = crud.get_error_article_ids(
        db,
        article_ids=None if body.all_errors else body.article_ids,
        feed_ids=body.feed_ids if body.all_errors else None,
    )
    if ids:
        # Leave the Error group right away so the same article isn't queued twice.
        crud.mark_articles_pending(db, ids)
        from app.tasks.background import register_reprocess, reprocess_articles_task
        register_reprocess(len(ids))
        background_tasks.add_task(reprocess_articles_task, ids)
    return {"queued": len(ids), "article_ids": ids}


@router.get("/reprocess-status")
async def get_reprocess_status():
    """Progress of the re-process job: {status: idle|running|done, total, done, failed}."""
    from app.tasks.background import get_reprocess_status as _get_status
    return _get_status()


@router.get("/counts")
async def get_article_counts(db: Session = Depends(get_db)):
    """Get article counts grouped by priority and feed.

    by_priority/unimportant_count are scoped to unread articles — they back the
    sidebar filter badges, which are meant to read as "how many are left to
    triage", so they should drop as articles are archived, not just deleted.
    """
    from sqlalchemy import func
    # Error articles (unlabelled or failed) are not "unread work" — they are counted in
    # error_count and listed in the Error tab instead.
    not_error = ~crud.error_clause()

    priority_rows = db.query(
        models.Article.priority,
        func.count(models.Article.id)
    ).filter(
        models.Article.priority.isnot(None),
        models.Article.is_read.is_(False),
        not_error,
    ).group_by(models.Article.priority).all()

    feed_rows = db.query(
        models.Article.feed_id,
        func.count(models.Article.id)
    ).filter(
        models.Article.is_read.is_(False),
        not_error,
    ).group_by(models.Article.feed_id).all()

    unimportant_count = db.query(func.count(models.Article.id)).filter(
        models.Article.importance == "unimportant",
        models.Article.is_read.is_(False),
        not_error,
    ).scalar() or 0

    unread_count = db.query(func.count(models.Article.id)).filter(
        models.Article.is_read.is_(False),
        not_error,
    ).scalar() or 0

    read_count = db.query(func.count(models.Article.id)).filter(
        models.Article.is_read.is_(True)
    ).scalar() or 0

    starred_count = db.query(func.count(models.Article.id)).filter(
        models.Article.is_starred.is_(True)
    ).scalar() or 0

    error_count = crud.count_error_articles(db)

    return {
        "by_priority": {p: c for p, c in priority_rows},
        "by_feed": {str(f): c for f, c in feed_rows},
        "unimportant_count": unimportant_count,
        "unread_count": unread_count,
        "read_count": read_count,
        "starred_count": starred_count,
        "error_count": error_count,
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
        "image_url": article.image_url,
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
        "is_starred": article.is_starred,
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
            "image_url": article.image_url,
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
            "is_starred": article.is_starred,
        }
        articles_response.append(ArticleResponse(**article_data))
    
    return ArticleListResponse(
        articles=articles_response,
        total=total,
        skip=skip,
        limit=limit
    )
