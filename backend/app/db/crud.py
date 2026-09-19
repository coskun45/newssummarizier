"""
CRUD (Create, Read, Update, Delete) operations for database models.
"""
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import desc, func, or_, case
from typing import List, Optional, Dict, Any, Set
from datetime import datetime, timezone
from app.db import models


# ==================== Feed Operations ====================

def create_feed(db: Session, url: str, title: str = None, description: str = None) -> models.Feed:
    """Create a new RSS feed."""
    feed = models.Feed(url=url, title=title, description=description)
    db.add(feed)
    db.commit()
    db.refresh(feed)
    return feed


def get_feed(db: Session, feed_id: int) -> Optional[models.Feed]:
    """Get a feed by ID."""
    return db.query(models.Feed).filter(models.Feed.id == feed_id).first()


def get_feed_by_url(db: Session, url: str) -> Optional[models.Feed]:
    """Get a feed by URL."""
    return db.query(models.Feed).filter(models.Feed.url == url).first()


def get_feeds(db: Session, active_only: bool = True) -> List[models.Feed]:
    """Get all feeds."""
    query = db.query(models.Feed)
    if active_only:
        query = query.filter(models.Feed.is_active)
    return query.all()


def update_feed_last_fetched(db: Session, feed_id: int) -> Optional[models.Feed]:
    """Update feed's last fetched timestamp."""
    feed = get_feed(db, feed_id)
    if feed:
        feed.last_fetched = datetime.now(timezone.utc)
        db.commit()
        db.refresh(feed)
    return feed


def update_feed(
    db: Session,
    feed_id: int,
    url: str = None,
    title: str = None,
    description: str = None,
    is_active: bool = None,
) -> Optional[models.Feed]:
    """Update a feed's editable fields. Only provided fields are changed."""
    feed = get_feed(db, feed_id)
    if feed:
        if url is not None:
            feed.url = url
        if title is not None:
            feed.title = title
        if description is not None:
            feed.description = description
        if is_active is not None:
            feed.is_active = is_active
        db.commit()
        db.refresh(feed)
    return feed


def delete_feed(db: Session, feed_id: int) -> bool:
    """Delete a feed."""
    feed = get_feed(db, feed_id)
    if feed:
        db.delete(feed)
        db.commit()
        return True
    return False


# ==================== Article Operations ====================

def create_article(
    db: Session,
    feed_id: int,
    url: str,
    title: str,
    author: str = None,
    published_at: datetime = None,
    raw_content: str = None,
    cleaned_content: str = None,
    image_url: str = None,
    status: str = "pending"
) -> models.Article:
    """Create a new article."""
    article = models.Article(
        feed_id=feed_id,
        url=url,
        title=title,
        author=author,
        published_at=published_at,
        raw_content=raw_content,
        cleaned_content=cleaned_content,
        image_url=image_url,
        status=status
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def get_article(db: Session, article_id: int) -> Optional[models.Article]:
    """Get an article by ID with relationships loaded."""
    return db.query(models.Article).options(
        selectinload(models.Article.summaries),
        selectinload(models.Article.topics).selectinload(models.ArticleTopic.topic)
    ).filter(models.Article.id == article_id).first()


def get_article_by_url(db: Session, url: str) -> Optional[models.Article]:
    """Get an article by URL."""
    return db.query(models.Article).filter(models.Article.url == url).first()


def _tombstone_url(db: Session, url: str) -> None:
    """Record a deleted article's URL so RSS re-ingestion skips it forever.
    Caller commits — this only stages the insert."""
    exists = db.query(models.DeletedArticleUrl.url).filter(
        models.DeletedArticleUrl.url == url
    ).first()
    if not exists:
        db.add(models.DeletedArticleUrl(url=url))


def get_deleted_urls(db: Session) -> Set[str]:
    """All tombstoned URLs, for a single bulk dedup check during RSS ingestion."""
    return {row[0] for row in db.query(models.DeletedArticleUrl.url).all()}


def delete_article(db: Session, article_id: int) -> bool:
    """Delete an article by ID and tombstone its URL. Returns False if not found."""
    article = get_article(db, article_id)
    if not article:
        return False
    _tombstone_url(db, article.url)
    db.delete(article)
    db.commit()
    return True


ERROR_EXCLUDED_STATUSES = ("pending", "scraped")


def _unlabelled_clause():
    """No severity label: no priority and not marked unimportant (Önemsiz)."""
    return models.Article.priority.is_(None) & or_(
        models.Article.importance.is_(None), models.Article.importance != "unimportant"
    )


def error_clause():
    """SQL clause for the "Error" group: articles that could not be fully processed —
    either they never received a severity label, or they ended up `failed` (e.g. labelled
    but no summary could be generated). Articles still being processed (pending/scraped)
    are excluded so in-flight work isn't flagged as an error."""
    return (
        (_unlabelled_clause() | (models.Article.status == "failed"))
        & models.Article.status.notin_(ERROR_EXCLUDED_STATUSES)
    )


def get_articles(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    topic_ids: List[int] = None,
    search_query: str = None,
    status: str = None,
    start_date: datetime = None,
    end_date: datetime = None,
    fetched_from: datetime = None,
    fetched_to: datetime = None,
    feed_id: int = None,
    feed_ids: List[int] = None,
    priority: str = None,
    priorities: List[str] = None,
    is_read: bool = None,
    is_starred: bool = None,
    is_error: bool = None,
) -> List[models.Article]:
    """Get articles with optional filtering."""
    query = db.query(models.Article).options(
        selectinload(models.Article.summaries),
        selectinload(models.Article.topics).selectinload(models.ArticleTopic.topic)
    )

    # Filter by feed(s)
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    elif feed_id:
        query = query.filter(models.Article.feed_id == feed_id)

    # Filter by topic — use a subquery instead of a join so an article that
    # matches several of the selected topics is returned once, not duplicated
    # (a plain join multiplies rows and breaks limit/offset paging).
    if topic_ids:
        article_ids_with_topics = db.query(models.ArticleTopic.article_id).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        )
        query = query.filter(models.Article.id.in_(article_ids_with_topics))

    # Filter by status
    if status:
        query = query.filter(models.Article.status == status)

    # Filter by priority — a single value or a list (list wins if both given)
    if priorities:
        query = query.filter(models.Article.priority.in_(priorities))
    elif priority:
        query = query.filter(models.Article.priority == priority)

    # Filter by is_read
    if is_read is not None:
        query = query.filter(models.Article.is_read == is_read)

    # Filter by is_starred (user-curated "Önemli" group)
    if is_starred is not None:
        query = query.filter(models.Article.is_starred == is_starred)

    # Filter by "Error" group (no severity label): True = only errors, False = exclude them
    if is_error is not None:
        query = query.filter(error_clause() if is_error else ~error_clause())

    # Filter by published date range
    if start_date:
        query = query.filter(models.Article.published_at >= start_date)
    if end_date:
        query = query.filter(models.Article.published_at <= end_date)

    # Filter by fetched date range
    if fetched_from:
        query = query.filter(models.Article.fetched_at >= fetched_from)
    if fetched_to:
        query = query.filter(models.Article.fetched_at <= fetched_to)

    # Search in title and content
    if search_query:
        search_filter = or_(
            models.Article.title.ilike(f"%{search_query}%"),
            models.Article.cleaned_content.ilike(f"%{search_query}%")
        )
        query = query.filter(search_filter)

    # Order by published date descending
    query = query.order_by(desc(models.Article.published_at))

    return query.offset(skip).limit(limit).all()


def count_articles(
    db: Session,
    topic_ids: List[int] = None,
    search_query: str = None,
    status: str = None,
    feed_id: int = None,
    feed_ids: List[int] = None,
    priority: str = None,
    priorities: List[str] = None,
    start_date: datetime = None,
    end_date: datetime = None,
    fetched_from: datetime = None,
    fetched_to: datetime = None,
    is_read: bool = None,
    is_starred: bool = None,
    is_error: bool = None,
) -> int:
    """Count articles with optional filtering."""
    query = db.query(func.count(models.Article.id))

    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    elif feed_id:
        query = query.filter(models.Article.feed_id == feed_id)

    if topic_ids:
        article_ids_with_topics = db.query(models.ArticleTopic.article_id).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        )
        query = query.filter(models.Article.id.in_(article_ids_with_topics))

    if status:
        query = query.filter(models.Article.status == status)

    if priorities:
        query = query.filter(models.Article.priority.in_(priorities))
    elif priority:
        query = query.filter(models.Article.priority == priority)

    if is_read is not None:
        query = query.filter(models.Article.is_read == is_read)

    if is_starred is not None:
        query = query.filter(models.Article.is_starred == is_starred)

    if is_error is not None:
        query = query.filter(error_clause() if is_error else ~error_clause())

    if start_date:
        query = query.filter(models.Article.published_at >= start_date)
    if end_date:
        query = query.filter(models.Article.published_at <= end_date)

    if fetched_from:
        query = query.filter(models.Article.fetched_at >= fetched_from)
    if fetched_to:
        query = query.filter(models.Article.fetched_at <= fetched_to)

    if search_query:
        search_filter = or_(
            models.Article.title.ilike(f"%{search_query}%"),
            models.Article.cleaned_content.ilike(f"%{search_query}%")
        )
        query = query.filter(search_filter)

    return query.scalar()


def _bulletin_candidate_filter(query, priorities: List[str] = None, include_favorites: bool = False):
    """Union filter for bulletin candidates: articles matching any of `priorities`
    OR (if include_favorites) starred articles. Deliberately separate from
    get_articles'/count_articles' is_starred, which is always AND'd with other
    filters for the general article browser — don't reuse this for those."""
    if priorities and include_favorites:
        return query.filter(or_(models.Article.priority.in_(priorities), models.Article.is_starred.is_(True)))
    if priorities:
        return query.filter(models.Article.priority.in_(priorities))
    if include_favorites:
        return query.filter(models.Article.is_starred.is_(True))
    return query


def get_bulletin_candidate_articles(
    db: Session,
    start_date: datetime = None,
    end_date: datetime = None,
    priorities: List[str] = None,
    include_favorites: bool = False,
    skip: int = 0,
    limit: int = 100,
) -> List[models.Article]:
    """Articles eligible for bulletin generation: within the date range AND
    (priority-matched OR starred, per include_favorites)."""
    query = db.query(models.Article).options(
        selectinload(models.Article.summaries),
        selectinload(models.Article.topics).selectinload(models.ArticleTopic.topic)
    )
    query = _bulletin_candidate_filter(query, priorities, include_favorites)

    if start_date:
        query = query.filter(models.Article.published_at >= start_date)
    if end_date:
        query = query.filter(models.Article.published_at <= end_date)

    query = query.order_by(desc(models.Article.published_at))
    return query.offset(skip).limit(limit).all()


def count_bulletin_candidate_articles(
    db: Session,
    start_date: datetime = None,
    end_date: datetime = None,
    priorities: List[str] = None,
    include_favorites: bool = False,
) -> int:
    """Count version of get_bulletin_candidate_articles, for the live preview count."""
    query = db.query(func.count(models.Article.id))
    query = _bulletin_candidate_filter(query, priorities, include_favorites)

    if start_date:
        query = query.filter(models.Article.published_at >= start_date)
    if end_date:
        query = query.filter(models.Article.published_at <= end_date)

    return query.scalar()


def update_article_status(db: Session, article_id: int, status: str) -> Optional[models.Article]:
    """Update article status."""
    article = get_article(db, article_id)
    if article:
        article.status = status
        db.commit()
        db.refresh(article)
    return article


def mark_article_read(db: Session, article_id: int) -> Optional[models.Article]:
    """Mark an article as read by the user."""
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if article:
        article.is_read = True
        db.commit()
        db.refresh(article)
    return article


def mark_articles_read_bulk(
    db: Session,
    article_ids: Optional[List[int]] = None,
    topic_ids: List[int] = None,
    search_query: str = None,
    status: str = None,
    feed_id: int = None,
    feed_ids: List[int] = None,
    priority: str = None,
    start_date: datetime = None,
    end_date: datetime = None,
    fetched_from: datetime = None,
    fetched_to: datetime = None,
    is_starred: bool = None,
    is_error: bool = None,
) -> int:
    """Mark multiple articles as read. If article_ids is given, marks just those.
    Otherwise marks every unread article matching the given filters (no filters = all unread)."""
    query = db.query(models.Article).filter(models.Article.is_read.is_(False))
    if article_ids is not None:
        query = query.filter(models.Article.id.in_(article_ids))
    else:
        if feed_ids:
            query = query.filter(models.Article.feed_id.in_(feed_ids))
        elif feed_id:
            query = query.filter(models.Article.feed_id == feed_id)

        if topic_ids:
            article_ids_with_topics = db.query(models.ArticleTopic.article_id).filter(
                models.ArticleTopic.topic_id.in_(topic_ids)
            )
            query = query.filter(models.Article.id.in_(article_ids_with_topics))

        if status:
            query = query.filter(models.Article.status == status)

        if priority:
            query = query.filter(models.Article.priority == priority)

        if is_starred is not None:
            query = query.filter(models.Article.is_starred == is_starred)

        if is_error is not None:
            query = query.filter(error_clause() if is_error else ~error_clause())

        if start_date:
            query = query.filter(models.Article.published_at >= start_date)
        if end_date:
            query = query.filter(models.Article.published_at <= end_date)

        if fetched_from:
            query = query.filter(models.Article.fetched_at >= fetched_from)
        if fetched_to:
            query = query.filter(models.Article.fetched_at <= fetched_to)

        if search_query:
            search_filter = or_(
                models.Article.title.ilike(f"%{search_query}%"),
                models.Article.cleaned_content.ilike(f"%{search_query}%")
            )
            query = query.filter(search_filter)

    count = query.update({models.Article.is_read: True}, synchronize_session=False)
    db.commit()
    return count


def count_error_articles(db: Session) -> int:
    """Number of articles in the "Error" group (no severity label)."""
    return db.query(func.count(models.Article.id)).filter(error_clause()).scalar() or 0


def get_error_article_ids(
    db: Session,
    article_ids: Optional[List[int]] = None,
    feed_ids: Optional[List[int]] = None,
) -> List[int]:
    """Ids of articles currently in the "Error" group, optionally restricted to
    `article_ids` and/or `feed_ids`. Ids that aren't errors are silently dropped."""
    query = db.query(models.Article.id).filter(error_clause())
    if article_ids is not None:
        query = query.filter(models.Article.id.in_(article_ids))
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    return [row[0] for row in query.order_by(desc(models.Article.published_at)).all()]


def mark_article_unread(db: Session, article_id: int) -> Optional[models.Article]:
    """Put an article back into the unread list (used once a re-processed Error article got a label)."""
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if article:
        article.is_read = False
        db.commit()
        db.refresh(article)
    return article


def mark_articles_pending(db: Session, article_ids: List[int]) -> int:
    """Flag articles as pending (queued for re-processing) so they leave the Error group."""
    if not article_ids:
        return 0
    count = db.query(models.Article).filter(models.Article.id.in_(article_ids)).update(
        {models.Article.status: "pending"}, synchronize_session=False
    )
    db.commit()
    return count


def reset_stale_pending_articles(db: Session) -> int:
    """Move articles stuck in "pending" to "failed". Only safe at startup, when no pipeline or
    re-process job can be running: a crash/restart mid-run otherwise strands them as
    "pending", which the Error group excludes, so they could never be retried."""
    count = db.query(models.Article).filter(models.Article.status == "pending").update(
        {models.Article.status: "failed"}, synchronize_session=False
    )
    db.commit()
    return count


def fix_summarized_status(db: Session) -> int:
    """Normalize legacy rows: "summarized" is reserved for articles that have at least one
    summary AND a severity label. Anything else marked "summarized" (older pipeline runs
    that swallowed a failed categorization/summarization) becomes "failed". Idempotent.
    Returns the number of articles changed."""
    has_summary = db.query(models.Summary.id).filter(models.Summary.article_id == models.Article.id).exists()
    count = db.query(models.Article).filter(
        models.Article.status == "summarized",
        or_(~has_summary, _unlabelled_clause()),
    ).update({models.Article.status: "failed"}, synchronize_session=False)
    db.commit()
    return count


def set_article_starred(db: Session, article_id: int, starred: bool) -> Optional[models.Article]:
    """Add/remove an article from the user-curated 'Önemli' group."""
    article = db.query(models.Article).filter(models.Article.id == article_id).first()
    if article:
        article.is_starred = starred
        db.commit()
        db.refresh(article)
    return article


def unstar_all(db: Session) -> int:
    """Clear the whole 'Önemli' group. Returns the number of articles unstarred."""
    count = db.query(models.Article).filter(models.Article.is_starred.is_(True)).update(
        {models.Article.is_starred: False}, synchronize_session=False
    )
    db.commit()
    return count


def get_article_ids_by_topic(db: Session, topic_id: int) -> List[int]:
    """All article ids tagged with this topic, regardless of status."""
    rows = db.query(models.ArticleTopic.article_id).filter(
        models.ArticleTopic.topic_id == topic_id
    ).all()
    return [r[0] for r in rows]


def delete_articles_by_priority(db: Session, priority: str, feed_ids: List[int] = None) -> int:
    """Delete every unread article with this priority, optionally scoped to a
    set of feeds. Returns the number deleted.

    Uses a per-row ORM delete (not bulk Query.delete()) so the
    cascade="all, delete-orphan" relationships on Article (summaries, topics,
    logs) actually fire.
    """
    query = db.query(models.Article).filter(
        models.Article.priority == priority,
        models.Article.is_read.is_(False),
    )
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    articles = query.all()
    count = len(articles)
    for article in articles:
        _tombstone_url(db, article.url)
        db.delete(article)
    db.commit()
    return count


def mark_articles_read_by_priority(db: Session, priority: str, feed_ids: List[int] = None) -> int:
    """Mark every unread article with this priority as read, optionally
    scoped to a set of feeds. Returns the number updated."""
    query = db.query(models.Article).filter(
        models.Article.priority == priority,
        models.Article.is_read.is_(False),
    )
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    count = query.update({models.Article.is_read: True}, synchronize_session=False)
    db.commit()
    return count


def delete_articles_unimportant(db: Session, feed_ids: List[int] = None) -> int:
    """Delete every unread article marked unimportant, optionally scoped to a
    set of feeds. Returns the number deleted.

    Mirrors delete_articles_by_priority but filters on importance == "unimportant"
    instead of a priority level. Uses a per-row ORM delete so the cascade
    relationships on Article (summaries, topics, logs) fire correctly.
    """
    query = db.query(models.Article).filter(
        models.Article.importance == "unimportant",
        models.Article.is_read.is_(False),
    )
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    articles = query.all()
    count = len(articles)
    for article in articles:
        _tombstone_url(db, article.url)
        db.delete(article)
    db.commit()
    return count


def mark_articles_read_unimportant(db: Session, feed_ids: List[int] = None) -> int:
    """Mark every unread unimportant article as read, optionally scoped to a
    set of feeds. Returns the number updated."""
    query = db.query(models.Article).filter(
        models.Article.importance == "unimportant",
        models.Article.is_read.is_(False)
    )
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    count = query.update({models.Article.is_read: True}, synchronize_session=False)
    db.commit()
    return count


def update_article_importance(
    db: Session,
    article_id: int,
    importance: str,
    priority: Optional[str] = None
) -> Optional[models.Article]:
    """Update article importance and priority."""
    article = get_article(db, article_id)
    if article:
        article.importance = importance
        article.priority = priority
        db.commit()
        db.refresh(article)
    return article


def update_article_author(db: Session, article_id: int, author: str) -> Optional[models.Article]:
    """Set an article's author (used to backfill from the page when RSS lacks one)."""
    article = get_article(db, article_id)
    if article and author:
        article.author = author
        db.commit()
        db.refresh(article)
    return article


def update_article_image(db: Session, article_id: int, image_url: str) -> Optional[models.Article]:
    """Set an article's image (used to backfill from the page's og:image when RSS lacks one)."""
    article = get_article(db, article_id)
    if article and image_url:
        article.image_url = image_url
        db.commit()
        db.refresh(article)
    return article


def update_article_content(
    db: Session,
    article_id: int,
    raw_content: str = None,
    cleaned_content: str = None
) -> Optional[models.Article]:
    """Update article content."""
    article = get_article(db, article_id)
    if article:
        if raw_content is not None:
            article.raw_content = raw_content
        if cleaned_content is not None:
            article.cleaned_content = cleaned_content
        db.commit()
        db.refresh(article)
    return article


# ==================== Summary Operations ====================

def create_summary(
    db: Session,
    article_id: int,
    summary_text: str,
    summary_type: str,
    model_used: str,
    tokens_used: int,
    cost: float
) -> models.Summary:
    """Create a new summary."""
    summary = models.Summary(
        article_id=article_id,
        summary_text=summary_text,
        summary_type=summary_type,
        model_used=model_used,
        tokens_used=tokens_used,
        cost=cost
    )
    db.add(summary)
    db.commit()
    db.refresh(summary)
    return summary


def get_summary(db: Session, summary_id: int) -> Optional[models.Summary]:
    """Get a summary by ID."""
    return db.query(models.Summary).filter(models.Summary.id == summary_id).first()


def get_summaries_by_article(
    db: Session,
    article_id: int,
    summary_type: str = None
) -> List[models.Summary]:
    """Get all summaries for an article."""
    query = db.query(models.Summary).filter(models.Summary.article_id == article_id)
    if summary_type:
        query = query.filter(models.Summary.summary_type == summary_type)
    return query.all()


def get_total_cost(db: Session, start_date: datetime = None, end_date: datetime = None) -> float:
    """Calculate total API costs."""
    query = db.query(func.sum(models.Summary.cost))
    
    if start_date:
        query = query.filter(models.Summary.created_at >= start_date)
    if end_date:
        query = query.filter(models.Summary.created_at <= end_date)
    
    result = query.scalar()
    return result if result else 0.0


def get_daily_cost(db: Session) -> float:
    """Get today's API costs."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return get_total_cost(db, start_date=today)


def get_monthly_cost(db: Session) -> float:
    """Get this month's API costs."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return get_total_cost(db, start_date=month_start)


# ==================== Topic Operations ====================

def create_topic(db: Session, name: str, description: str = None, color: str = None) -> models.Topic:
    """Create a new topic."""
    topic = models.Topic(name=name, description=description, color=color)
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def get_topic(db: Session, topic_id: int) -> Optional[models.Topic]:
    """Get a topic by ID."""
    return db.query(models.Topic).filter(models.Topic.id == topic_id).first()


def get_topic_by_name(db: Session, name: str) -> Optional[models.Topic]:
    """Get a topic by name."""
    return db.query(models.Topic).filter(models.Topic.name == name).first()


def get_topics(db: Session) -> List[models.Topic]:
    """Get all topics."""
    return db.query(models.Topic).all()


def get_topics_with_counts(db: Session, feed_id: int = None) -> List[Dict[str, Any]]:
    """Get all topics with total and unread article counts, optionally filtered by feed."""
    query = db.query(
        models.Topic,
        func.count(models.ArticleTopic.article_id).label('article_count'),
        # Error articles (no severity label) don't count as unread — they live in the Error tab
        func.sum(case((models.Article.is_read.is_(False) & ~error_clause(), 1), else_=0)).label('unread_count')
    ).outerjoin(
        models.ArticleTopic,
        models.ArticleTopic.topic_id == models.Topic.id
    ).outerjoin(
        models.Article,
        models.Article.id == models.ArticleTopic.article_id
    )

    if feed_id is not None:
        query = query.filter(models.Article.feed_id == feed_id)

    results = query.group_by(models.Topic.id).having(
        func.count(models.ArticleTopic.article_id) > 0
    ).all() if feed_id is not None else query.group_by(models.Topic.id).all()

    return [
        {
            "id": topic.id,
            "name": topic.name,
            "description": topic.description,
            "color": topic.color,
            "article_count": article_count,
            "unread_count": int(unread_count or 0),
        }
        for topic, article_count, unread_count in results
    ]


def update_topic(
    db: Session,
    topic_id: int,
    name: str = None,
    description: str = None,
    color: str = None
) -> Optional[models.Topic]:
    """Update a topic."""
    topic = get_topic(db, topic_id)
    if topic:
        if name is not None:
            topic.name = name
        if description is not None:
            topic.description = description
        if color is not None:
            topic.color = color
        db.commit()
        db.refresh(topic)
    return topic


def delete_topic(db: Session, topic_id: int) -> bool:
    """Delete a topic."""
    topic = get_topic(db, topic_id)
    if topic:
        # First remove all article-topic associations
        db.query(models.ArticleTopic).filter(
            models.ArticleTopic.topic_id == topic_id
        ).delete()
        # Then delete the topic
        db.delete(topic)
        db.commit()
        return True
    return False


# ==================== Article-Topic Operations ====================

def add_article_topic(
    db: Session,
    article_id: int,
    topic_id: int,
    confidence: float = 1.0
) -> models.ArticleTopic:
    """Add a topic to an article."""
    article_topic = models.ArticleTopic(
        article_id=article_id,
        topic_id=topic_id,
        confidence=confidence
    )
    db.add(article_topic)
    db.commit()
    db.refresh(article_topic)
    return article_topic


def remove_article_topics(db: Session, article_id: int):
    """Remove all topics from an article."""
    db.query(models.ArticleTopic).filter(
        models.ArticleTopic.article_id == article_id
    ).delete()
    db.commit()


def delete_article_summaries(db: Session, article_id: int) -> int:
    """Remove all summaries of an article (used before re-processing). Returns the number deleted."""
    count = db.query(models.Summary).filter(
        models.Summary.article_id == article_id
    ).delete(synchronize_session=False)
    db.commit()
    return count


# ==================== Processing Log Operations ====================

def create_log(
    db: Session,
    article_id: int,
    agent_name: str,
    status: str,
    message: str,
    error_details: str = None
) -> models.ProcessingLog:
    """Create a processing log entry."""
    log = models.ProcessingLog(
        article_id=article_id,
        agent_name=agent_name,
        status=status,
        message=message,
        error_details=error_details
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_article_logs(db: Session, article_id: int) -> List[models.ProcessingLog]:
    """Get all logs for an article."""
    return db.query(models.ProcessingLog).filter(
        models.ProcessingLog.article_id == article_id
    ).order_by(models.ProcessingLog.created_at).all()


# ==================== Settings Operations ====================

def get_setting(db: Session, key: str) -> Optional[str]:
    """Get a setting value."""
    setting = db.query(models.Settings).filter(models.Settings.key == key).first()
    return setting.value if setting else None


def set_setting(db: Session, key: str, value: str) -> models.Settings:
    """Set a setting value."""
    setting = db.query(models.Settings).filter(models.Settings.key == key).first()
    if setting:
        setting.value = value
        setting.updated_at = datetime.now(timezone.utc)
    else:
        setting = models.Settings(key=key, value=value)
        db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


# ==================== System Prompt Operations ====================

def get_system_prompt(db: Session, prompt_type: str) -> Optional[models.SystemPrompt]:
    """Get a system prompt by type."""
    return db.query(models.SystemPrompt).filter(
        models.SystemPrompt.prompt_type == prompt_type
    ).first()


def get_all_system_prompts(db: Session) -> List[models.SystemPrompt]:
    """Get all system prompts."""
    return db.query(models.SystemPrompt).all()


def create_system_prompt(
    db: Session,
    prompt_type: str,
    prompt_text: str,
    is_active: bool = True
) -> models.SystemPrompt:
    """Create a new system prompt."""
    prompt = models.SystemPrompt(
        prompt_type=prompt_type,
        prompt_text=prompt_text,
        is_active=is_active
    )
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


def update_system_prompt(
    db: Session,
    prompt_type: str,
    prompt_text: str = None,
    is_active: bool = None
) -> Optional[models.SystemPrompt]:
    """Update an existing system prompt."""
    prompt = get_system_prompt(db, prompt_type)
    if prompt:
        if prompt_text is not None:
            prompt.prompt_text = prompt_text
        if is_active is not None:
            prompt.is_active = is_active
        prompt.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(prompt)
    return prompt


def upsert_system_prompt(
    db: Session,
    prompt_type: str,
    prompt_text: str,
    is_active: bool = True
) -> models.SystemPrompt:
    """Create or update a system prompt."""
    prompt = get_system_prompt(db, prompt_type)
    if prompt:
        prompt.prompt_text = prompt_text
        prompt.is_active = is_active
        prompt.updated_at = datetime.now(timezone.utc)
    else:
        prompt = models.SystemPrompt(
            prompt_type=prompt_type,
            prompt_text=prompt_text,
            is_active=is_active
        )
        db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


# ==================== User Operations ====================

def get_user(db: Session, user_id: int) -> Optional[models.User]:
    """Get a user by ID."""
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    """Get a user by email address."""
    return db.query(models.User).filter(models.User.email == email).first()


def get_users(db: Session) -> List[models.User]:
    """Get all users ordered by creation date."""
    return db.query(models.User).order_by(models.User.created_at).all()


def create_user(
    db: Session,
    email: str,
    hashed_password: str,
    role: str = "user"
) -> models.User:
    """Create a new user with a hashed password."""
    user = models.User(email=email, hashed_password=hashed_password, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    """Delete a user by ID. Returns True if deleted, False if not found."""
    user = get_user(db, user_id)
    if user:
        db.delete(user)
        db.commit()
        return True
    return False


# ==================== Bulletin Category Operations ====================

def get_bulletin_categories(db: Session) -> List[models.BulletinCategory]:
    """Get all bulletin top-level categories, ordered for display."""
    return db.query(models.BulletinCategory).order_by(models.BulletinCategory.display_order).all()


def get_bulletin_category(db: Session, category_id: int) -> Optional[models.BulletinCategory]:
    """Get a bulletin category by ID."""
    return db.query(models.BulletinCategory).filter(models.BulletinCategory.id == category_id).first()


# Fold all four Turkish I-variants to the same character before lowercasing,
# matching app.services.docx_service._normalize() exactly — two category
# names that only differ by case/Turkish-I form (e.g. "Avrupa" / "AVRUPA")
# would otherwise both be created and then collide onto the same template
# heading when rendering a bulletin (docx_service._rebuild_category_sections).
_BULLETIN_CATEGORY_TR_I_FOLD = str.maketrans({"İ": "i", "I": "i", "ı": "i"})


def _normalize_bulletin_category_name(name: str) -> str:
    return name.strip().translate(_BULLETIN_CATEGORY_TR_I_FOLD).lower()


def get_bulletin_category_by_name(db: Session, name: str) -> Optional[models.BulletinCategory]:
    """Get a bulletin category by name, case/Turkish-I-insensitively."""
    target = _normalize_bulletin_category_name(name)
    for category in db.query(models.BulletinCategory).all():
        if _normalize_bulletin_category_name(category.name) == target:
            return category
    return None


def create_bulletin_category(db: Session, name: str) -> models.BulletinCategory:
    """Create a new bulletin category, appended to the end of the display order."""
    max_order = db.query(func.max(models.BulletinCategory.display_order)).scalar()
    category = models.BulletinCategory(name=name, display_order=(max_order or 0) + 1)
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


def update_bulletin_category(db: Session, category_id: int, name: str = None) -> Optional[models.BulletinCategory]:
    """Update a bulletin category's name."""
    category = get_bulletin_category(db, category_id)
    if category:
        if name is not None:
            category.name = name
        db.commit()
        db.refresh(category)
    return category


def delete_bulletin_category(db: Session, category_id: int) -> bool:
    """Delete a bulletin category."""
    category = get_bulletin_category(db, category_id)
    if category:
        db.delete(category)
        db.commit()
        return True
    return False


def reorder_bulletin_categories(db: Session, ordered_ids: List[int]) -> List[models.BulletinCategory]:
    """Rewrite display_order to match the given id order. IDs not present are
    left at the end, in their previous relative order."""
    categories = {c.id: c for c in get_bulletin_categories(db)}
    order = 0
    for category_id in ordered_ids:
        category = categories.pop(category_id, None)
        if category:
            category.display_order = order
            order += 1
    for category in categories.values():
        category.display_order = order
        order += 1
    db.commit()
    return get_bulletin_categories(db)


# ==================== Bulletin Classification Operations ====================

def get_bulletin_classifications(
    db: Session,
    article_ids: List[int],
    category_set_hash: str,
) -> Dict[int, models.ArticleBulletinClassification]:
    """Cached classifications for the given articles under this category set,
    keyed by article_id."""
    if not article_ids:
        return {}
    rows = db.query(models.ArticleBulletinClassification).filter(
        models.ArticleBulletinClassification.article_id.in_(article_ids),
        models.ArticleBulletinClassification.category_set_hash == category_set_hash,
    ).all()
    return {row.article_id: row for row in rows}


def create_bulletin_classification(
    db: Session,
    article_id: int,
    category_set_hash: str,
    top_category: str,
    subcategory: str,
    article_type: str,
    model_used: str = None,
) -> models.ArticleBulletinClassification:
    """Persist a bulletin classification result for an article/category-set pair."""
    classification = models.ArticleBulletinClassification(
        article_id=article_id,
        category_set_hash=category_set_hash,
        top_category=top_category,
        subcategory=subcategory,
        article_type=article_type,
        model_used=model_used,
    )
    db.add(classification)
    db.commit()
    db.refresh(classification)
    return classification


# ==================== Generated Bulletin Operations ====================

def get_generated_bulletins(db: Session) -> List[models.GeneratedBulletin]:
    """Previously generated bulletin reports, newest first. SQLite's
    CURRENT_TIMESTAMP has 1-second resolution, so two reports generated
    within the same second would tie on generated_at — break ties by id
    (insertion order) so "newest first" is never ambiguous."""
    return db.query(models.GeneratedBulletin).order_by(
        desc(models.GeneratedBulletin.generated_at), desc(models.GeneratedBulletin.id)
    ).all()


def get_generated_bulletin(db: Session, bulletin_id: int) -> Optional[models.GeneratedBulletin]:
    return db.query(models.GeneratedBulletin).filter(models.GeneratedBulletin.id == bulletin_id).first()


def create_generated_bulletin(
    db: Session,
    filename: str,
    stored_path: str,
    published_from: Optional[datetime],
    published_to: Optional[datetime],
    priorities: Optional[str],
    include_favorites: bool,
    article_count: int,
) -> models.GeneratedBulletin:
    """Record a newly generated bulletin report for later listing/re-download."""
    row = models.GeneratedBulletin(
        filename=filename,
        stored_path=stored_path,
        published_from=published_from,
        published_to=published_to,
        priorities=priorities,
        include_favorites=include_favorites,
        article_count=article_count,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_generated_bulletin(db: Session, bulletin_id: int) -> bool:
    row = get_generated_bulletin(db, bulletin_id)
    if row:
        db.delete(row)
        db.commit()
        return True
    return False

