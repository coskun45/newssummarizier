"""
Article endpoints.
"""
from anyio import from_thread
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import logging
import uuid
from typing import List, Literal, Optional
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone
from app.db.database import get_db
from app.db import crud, models
from app.api.deps import require_admin
from app.services import summary_service
from app.services.summary_service import article_source_name


router = APIRouter()
logger = logging.getLogger(__name__)


def _parse_comma_ids(raw: Optional[str], field_name: str) -> Optional[List[int]]:
    """Parse a comma-separated query/body string of ids into a list of ints."""
    if not raw:
        return None
    try:
        return [int(v) for v in raw.split(",")]
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format")


VALID_PRIORITIES = {"high", "med", "low"}
# Sidebar "Kaynak Türü" groups (crud.origin_clause).
ArticleOrigin = Literal["free_match", "manual"]


def _article_source(article: models.Article) -> Optional[str]:
    """The card's "Kaynak": the article's feed name (the same value the summary header uses)."""
    return article_source_name(article.feed.title if article.feed else None, article.url)


def _free_match(article: models.Article) -> Optional[dict]:
    match = article.free_match_article if article.content_access == "free_match" else None
    if match is None:
        return None
    return {"id": match.id, "title": match.title, "url": match.url, "source": _article_source(match)}


@router.delete("/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_article(article_id: int, db: Session = Depends(get_db)):
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


class FreeMatchInfo(BaseModel):
    """The free-source article with the same story as a blocked/paywalled one."""
    id: int
    title: str
    url: str
    source: Optional[str] = None


class ArticleResponse(BaseModel):
    """Article response model."""
    id: int
    url: str
    title: str
    author: Optional[str] = None
    source: Optional[str] = None
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
    # None = full text read; "free_match" (see free_match) | "unavailable" = the page gave no article
    content_access: Optional[str] = None
    free_match: Optional[FreeMatchInfo] = None
    source_type: str = "rss"  # "rss" | "manual"

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


def _to_article_response(article: models.Article, detail: bool = False):
    """Build the API shape of an article (list rows and the detail view share it)."""
    free_match = _free_match(article)
    data = {
        "id": article.id,
        "url": article.url,
        "title": article.title,
        "author": article.author,
        "source": _article_source(article),
        "published_at": article.published_at,
        "fetched_at": article.fetched_at,
        "status": article.status,
        "importance": article.importance,
        "priority": article.priority,
        "image_url": article.image_url,
        "topics": [
            {"id": at.topic.id, "name": at.topic.name, "color": at.topic.color, "confidence": at.confidence}
            for at in article.topics
        ],
        "has_summaries": len(article.summaries) > 0,
        "is_read": article.is_read,
        "is_starred": article.is_starred,
        # A "free_match" whose matched article was deleted has nothing to link to: no match.
        "content_access": "unavailable" if article.content_access == "free_match" and free_match is None
        else article.content_access,
        "free_match": free_match,
        "source_type": article.source_type or "rss",
    }
    if detail:
        return ArticleDetailResponse(**data, raw_content=article.raw_content, cleaned_content=article.cleaned_content)
    return ArticleResponse(**data)


@router.get("/", response_model=ArticleListResponse)
def list_articles(
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
    origin: Optional[ArticleOrigin] = Query(None, description="Sidebar 'Kaynak Türü': free_match = a free source has the story, manual = added by an admin"),
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
        origin=origin,
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
        origin=origin,
    )

    articles_response = [_to_article_response(article) for article in articles]

    return ArticleListResponse(
        articles=articles_response,
        total=total,
        skip=skip,
        limit=limit
    )


@router.patch("/{article_id}/read")
def mark_article_read(
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
    origin: Optional[ArticleOrigin] = None
    # "Bu ve üstündekileri/altındakileri arşive gönder": with mark_all, limit the filtered set to
    # the articles at/above or at/below this one in the list's order (anchor included).
    anchor_id: Optional[int] = None
    direction: Optional[Literal["above", "below"]] = None


@router.post("/mark-read-bulk")
def mark_articles_read_bulk(
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
    if (body.anchor_id is None) != (body.direction is None):
        raise HTTPException(status_code=400, detail="anchor_id and direction must be given together")
    if body.anchor_id is not None and not body.mark_all:
        raise HTTPException(status_code=400, detail="anchor_id requires mark_all=true")
    anchor = None
    if body.anchor_id is not None:
        anchor = crud.get_article(db, body.anchor_id)
        if not anchor:
            raise HTTPException(status_code=404, detail="Article not found")
    ids = None if body.mark_all else body.article_ids
    if ids is not None:
        count = crud.mark_articles_read_bulk(db, ids)
    else:
        count = crud.mark_articles_read_bulk(
            db,
            None,
            anchor=anchor,
            direction=body.direction,
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
            origin=body.origin,
        )
    return {"marked_count": count}


class StarRequest(BaseModel):
    """Request body for toggling an article's 'Önemli' (starred) state."""
    starred: bool = True


@router.patch("/{article_id}/star")
def star_article(article_id: int, body: StarRequest, db: Session = Depends(get_db)):
    """Add or remove an article from the user-curated 'Önemli' group."""
    article = crud.set_article_starred(db, article_id, body.starred)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return {"id": article_id, "is_starred": body.starred}


@router.post("/unstar-all")
def unstar_all_articles(db: Session = Depends(get_db)):
    """Clear the whole 'Önemli' group."""
    count = crud.unstar_all(db)
    return {"unstarred_count": count}


@router.get("/topic/{topic_id}/ids")
def get_article_ids_by_topic(topic_id: int, db: Session = Depends(get_db)):
    """All article ids tagged with this topic, regardless of status (used for 'select all' by category)."""
    if not crud.get_topic(db, topic_id):
        raise HTTPException(status_code=404, detail="Topic not found")
    return {"article_ids": crud.get_article_ids_by_topic(db, topic_id)}


@router.post("/priority/{priority}/delete-all")
def delete_articles_by_priority(
    priority: str,
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the delete to"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete every unread article with this priority, optionally scoped to feed_ids (admin only)."""
    if priority not in VALID_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority; expected one of: high, med, low")
    count = crud.delete_articles_by_priority(db, priority, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"deleted_count": count}


@router.post("/priority/{priority}/archive-all")
def archive_articles_by_priority(
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
def delete_articles_unimportant(
    feed_ids: Optional[str] = Query(None, description="Comma-separated feed IDs to scope the delete to"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete every unread unimportant article, optionally scoped to feed_ids (admin only)."""
    count = crud.delete_articles_unimportant(db, feed_ids=_parse_comma_ids(feed_ids, "feed IDs"))
    return {"deleted_count": count}


@router.post("/unimportant/archive-all")
def archive_articles_unimportant(
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
def reprocess_articles(
    body: ReprocessRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Re-run classification + summarization for "Error" articles (no severity label). Admin only —
    it spends OpenAI budget.
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
        # This route runs in the threadpool; _reprocess_status is also mutated by the task on
        # the event loop, so do the check-then-update there to keep the two from interleaving.
        from_thread.run_sync(register_reprocess, len(ids))
        background_tasks.add_task(reprocess_articles_task, ids)
    return {"queued": len(ids), "article_ids": ids}


MANUAL_MAX_ARTICLES = 50
MANUAL_URL_SCHEME = "manual://"


class ManualArticleIn(BaseModel):
    """One user-supplied article. The feed is given by id or by its title; at least one of
    content / url is needed (content skips the page fetch, a bare url gets it scraped)."""
    title: str = Field(..., min_length=3, max_length=500)
    feed_id: Optional[int] = None
    feed: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = Field(None, max_length=100_000)
    # Plain strings, kept as typed: HttpUrl would percent-encode / add a trailing "/", and the
    # duplicate check compares with URLs stored exactly as their feed gave them.
    url: Optional[str] = Field(None, max_length=2000)
    author: Optional[str] = Field(None, max_length=200)
    published_at: Optional[datetime] = None
    image_url: Optional[str] = Field(None, max_length=2000)

    @field_validator("title", "feed", "content", "author", "url", "image_url", mode="before")
    @classmethod
    def _strip(cls, v):
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v

    @field_validator("url", "image_url")
    @classmethod
    def _http_only(cls, v):
        if v is not None:
            parsed = urlparse(v)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("http:// veya https:// ile başlayan geçerli bir adres olmalı")
        return v

    @model_validator(mode="after")
    def _check_required(self):
        if self.feed_id is None and not self.feed:
            raise ValueError("feed_id veya feed (kaynak başlığı) gerekli")
        if not self.content and self.url is None:
            raise ValueError("content veya url alanlarından en az biri gerekli")
        return self


class ManualArticlesRequest(BaseModel):
    articles: List[ManualArticleIn] = Field(..., min_length=1, max_length=MANUAL_MAX_ARTICLES)


class ManualArticleCreated(BaseModel):
    index: int
    article_id: int
    title: str


class ManualArticleRejected(BaseModel):
    index: int
    title: str
    reason: str


class ManualArticlesResponse(BaseModel):
    created: List[ManualArticleCreated]
    skipped: List[ManualArticleRejected]
    errors: List[ManualArticleRejected]
    queued: int


@router.post("/manual", response_model=ManualArticlesResponse)
def create_manual_articles(
    body: ManualArticlesRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Add user-supplied articles (form or JSON upload) and run them through the same pipeline as
    feed articles (classify → topics → summaries). Admin only — it spends OpenAI budget.
    An entry whose feed isn't found (or is inactive) lands in `errors`, one whose URL already exists in `skipped`;
    the rest are created and queued. Progress: GET /reprocess-status.
    """
    created: List[ManualArticleCreated] = []
    skipped: List[ManualArticleRejected] = []
    errors: List[ManualArticleRejected] = []
    seen_urls = set()
    for index, item in enumerate(body.articles):
        # Only active feeds, like the dialog's feed list and preview (useFeeds → active_only).
        if item.feed_id is not None:
            feed = crud.get_feed(db, item.feed_id)
            feed = feed if feed is not None and feed.is_active else None
        else:
            feed = crud.get_feed_by_title(db, item.feed, active_only=True)
        if feed is None:
            errors.append(ManualArticleRejected(index=index, title=item.title, reason="Kaynak bulunamadı"))
            continue
        url = item.url or f"{MANUAL_URL_SCHEME}{uuid.uuid4()}"
        duplicate = ManualArticleRejected(index=index, title=item.title, reason="Bu URL ile bir haber zaten var")
        if url in seen_urls or crud.get_article_by_url(db, url):
            skipped.append(duplicate)
            continue
        seen_urls.add(url)
        # Each create commits on its own, so one failing entry must not abort the request: the
        # ones already stored would stay "pending" (outside the Error tab) and never be queued.
        try:
            article = crud.create_article(
                db,
                feed_id=feed.id,
                url=url,
                title=item.title,
                author=item.author,
                published_at=item.published_at or datetime.now(timezone.utc),
                raw_content=item.content,
                cleaned_content=item.content,
                image_url=item.image_url,
                status="pending",
                source_type="manual",
            )
        except IntegrityError:
            # The same URL was stored meanwhile (feed refresh / another upload).
            db.rollback()
            skipped.append(duplicate)
            continue
        except Exception:
            db.rollback()
            logger.exception("Manual article %d could not be stored", index)
            errors.append(ManualArticleRejected(index=index, title=item.title, reason="Haber kaydedilemedi"))
            continue
        created.append(ManualArticleCreated(index=index, article_id=article.id, title=article.title))

    ids = [c.article_id for c in created]
    if ids:
        from app.tasks.background import register_reprocess, reprocess_articles_task
        # Same queue as the Error re-process: one run at a time, progress on /reprocess-status.
        from_thread.run_sync(register_reprocess, len(ids))
        background_tasks.add_task(reprocess_articles_task, ids)
    return ManualArticlesResponse(created=created, skipped=skipped, errors=errors, queued=len(ids))


@router.get("/reprocess-status")
async def get_reprocess_status():
    """Progress of the re-process job: {status: idle|running|done, total, done, failed}."""
    from app.tasks.background import get_reprocess_status as _get_status
    return _get_status()


@router.get("/counts")
def get_article_counts(db: Session = Depends(get_db)):
    """Get article counts grouped by priority and feed.

    by_priority/unimportant_count are scoped to unread articles — they back the
    sidebar filter badges, which are meant to read as "how many are left to
    triage", so they should drop as articles are archived, not just deleted.
    """
    return crud.get_article_counts(db)


@router.get("/{article_id}", response_model=ArticleDetailResponse)
def get_article(article_id: int, db: Session = Depends(get_db)):
    """
    Get detailed article information.
    """
    article = crud.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    return _to_article_response(article, detail=True)


@router.get("/topic/{topic_name}")
def get_articles_by_topic(
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
    
    articles_response = [_to_article_response(article) for article in articles]

    return ArticleListResponse(
        articles=articles_response,
        total=total,
        skip=skip,
        limit=limit
    )


# Declared after the /topic/{topic_name} routes: otherwise GET /topic/content matches here (422).
@router.get("/{article_id}/content", response_model=ArticleDetailResponse)
async def get_article_content(article_id: int, db: Session = Depends(get_db)):
    """
    Article detail with its full page text ("Orijinal İçerik"). The pipeline only scrapes
    important articles, so a filtered/Error article's page is fetched and stored on first open.
    """
    if not crud.get_article(db, article_id):
        raise HTTPException(status_code=404, detail="Article not found")
    await summary_service.fetch_article_content(db, article_id)
    return _to_article_response(crud.get_article(db, article_id), detail=True)
