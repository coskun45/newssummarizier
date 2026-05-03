"""
CRUD (Create, Read, Update, Delete) operations for database models.
"""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func, or_
from typing import List, Optional, Dict, Any
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
        status=status
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    return article


def get_article(db: Session, article_id: int) -> Optional[models.Article]:
    """Get an article by ID with relationships loaded."""
    return db.query(models.Article).options(
        joinedload(models.Article.summaries),
        joinedload(models.Article.topics).joinedload(models.ArticleTopic.topic)
    ).filter(models.Article.id == article_id).first()


def get_article_by_url(db: Session, url: str) -> Optional[models.Article]:
    """Get an article by URL."""
    return db.query(models.Article).filter(models.Article.url == url).first()


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
    is_read: bool = None
) -> List[models.Article]:
    """Get articles with optional filtering."""
    query = db.query(models.Article).options(
        joinedload(models.Article.summaries),
        joinedload(models.Article.topics).joinedload(models.ArticleTopic.topic)
    )

    # Filter by feed(s)
    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    elif feed_id:
        query = query.filter(models.Article.feed_id == feed_id)

    # Filter by topic
    if topic_ids:
        query = query.join(models.ArticleTopic).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        )

    # Filter by status
    if status:
        query = query.filter(models.Article.status == status)

    # Filter by priority
    if priority:
        query = query.filter(models.Article.priority == priority)

    # Filter by is_read
    if is_read is not None:
        query = query.filter(models.Article.is_read == is_read)

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
    start_date: datetime = None,
    end_date: datetime = None,
    fetched_from: datetime = None,
    fetched_to: datetime = None,
    is_read: bool = None,
) -> int:
    """Count articles with optional filtering."""
    query = db.query(func.count(models.Article.id))

    if feed_ids:
        query = query.filter(models.Article.feed_id.in_(feed_ids))
    elif feed_id:
        query = query.filter(models.Article.feed_id == feed_id)

    if topic_ids:
        query = query.join(models.ArticleTopic).filter(
            models.ArticleTopic.topic_id.in_(topic_ids)
        )

    if status:
        query = query.filter(models.Article.status == status)

    if priority:
        query = query.filter(models.Article.priority == priority)

    if is_read is not None:
        query = query.filter(models.Article.is_read == is_read)

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


def mark_articles_read_bulk(db: Session, article_ids: Optional[List[int]] = None) -> int:
    """Mark multiple articles as read. If article_ids is None, marks all unread articles."""
    query = db.query(models.Article).filter(models.Article.is_read == False)
    if article_ids is not None:
        query = query.filter(models.Article.id.in_(article_ids))
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
    """Get all topics with article counts, optionally filtered by feed."""
    query = db.query(
        models.Topic,
        func.count(models.ArticleTopic.article_id).label('article_count')
    ).outerjoin(models.ArticleTopic)

    if feed_id is not None:
        query = query.outerjoin(
            models.Article,
            models.Article.id == models.ArticleTopic.article_id
        ).filter(models.Article.feed_id == feed_id)

    results = query.group_by(models.Topic.id).having(
        func.count(models.ArticleTopic.article_id) > 0
    ).all() if feed_id is not None else query.group_by(models.Topic.id).all()

    return [
        {
            "id": topic.id,
            "name": topic.name,
            "description": topic.description,
            "color": topic.color,
            "article_count": count
        }
        for topic, count in results
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

