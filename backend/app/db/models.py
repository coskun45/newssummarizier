"""
SQLAlchemy database models.
"""
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.database import Base, UTCDateTime


class Feed(Base):
    """RSS Feed model."""
    __tablename__ = "feeds"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    url = Column(String, unique=True, nullable=False, index=True)
    title = Column(String)
    description = Column(Text)
    last_fetched = Column(UTCDateTime())
    fetch_interval = Column(Integer, default=3600)  # seconds
    is_active = Column(Boolean, default=True)
    created_at = Column(UTCDateTime(), server_default=func.now())
    
    # Relationships
    articles = relationship("Article", back_populates="feed", cascade="all, delete-orphan")


class Article(Base):
    """News Article model."""
    __tablename__ = "articles"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    feed_id = Column(Integer, ForeignKey("feeds.id"), nullable=False)
    url = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    author = Column(String)
    published_at = Column(UTCDateTime())
    fetched_at = Column(UTCDateTime(), server_default=func.now())
    raw_content = Column(Text)  # Full HTML/text content
    cleaned_content = Column(Text)  # Extracted main content
    status = Column(String, default="pending", index=True)  # pending, scraped, summarized, failed, filtered
    importance = Column(String, nullable=True)  # "important" | "unimportant"
    priority = Column(String, nullable=True)    # "high" | "med" | "low"
    is_read = Column(Boolean, default=False, nullable=False)
    is_starred = Column(Boolean, default=False, nullable=False, index=True)  # User-curated "Önemli" group

    # Relationships
    feed = relationship("Feed", back_populates="articles")
    summaries = relationship("Summary", back_populates="article", cascade="all, delete-orphan")
    topics = relationship("ArticleTopic", back_populates="article", cascade="all, delete-orphan")
    logs = relationship("ProcessingLog", back_populates="article", cascade="all, delete-orphan")


class Summary(Base):
    """Article Summary model."""
    __tablename__ = "summaries"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    summary_text = Column(Text, nullable=False)
    summary_type = Column(String, default="standard")  # brief, standard, detailed
    model_used = Column(String)  # gpt-4, gpt-3.5-turbo, etc.
    tokens_used = Column(Integer)
    cost = Column(Float)  # Track API costs
    created_at = Column(UTCDateTime(), server_default=func.now())
    
    # Relationships
    article = relationship("Article", back_populates="summaries")


class Topic(Base):
    """Topic/Category model."""
    __tablename__ = "topics"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(Text)
    color = Column(String)  # For UI color coding
    
    # Relationships
    articles = relationship("ArticleTopic", back_populates="topic")


class ArticleTopic(Base):
    """Many-to-many relationship between Articles and Topics."""
    __tablename__ = "article_topics"
    
    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    topic_id = Column(Integer, ForeignKey("topics.id"), primary_key=True)
    confidence = Column(Float)  # Classification confidence 0-1
    
    # Relationships
    article = relationship("Article", back_populates="topics")
    topic = relationship("Topic", back_populates="articles")


class ProcessingLog(Base):
    """Processing log for debugging agent workflow."""
    __tablename__ = "processing_logs"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"))
    agent_name = Column(String)
    status = Column(String)  # success, error, skipped
    message = Column(Text)
    error_details = Column(Text)
    created_at = Column(UTCDateTime(), server_default=func.now())
    
    # Relationships
    article = relationship("Article", back_populates="logs")


class SystemPrompt(Base):
    """System prompts for AI operations."""
    __tablename__ = "system_prompts"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    prompt_type = Column(String, unique=True, nullable=False)  # 'classification', 'summarization'
    prompt_text = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(UTCDateTime(), server_default=func.now())
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class Settings(Base):
    """Application settings storage."""
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(Text)
    updated_at = Column(UTCDateTime(), server_default=func.now(), onupdate=func.now())


class DeletedArticleUrl(Base):
    """Tombstone for a URL the user explicitly deleted. Checked during RSS
    ingestion so a feed that still lists the item doesn't recreate it."""
    __tablename__ = "deleted_article_urls"

    url = Column(String, primary_key=True)
    deleted_at = Column(UTCDateTime(), server_default=func.now())


class BulletinCategory(Base):
    """User-editable top-level section of the Word bulletin report (e.g. "AVRUPA",
    "AMERİKA"). Independent of the ingestion pipeline's flat Topic taxonomy."""
    __tablename__ = "bulletin_categories"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(UTCDateTime(), server_default=func.now())


class ArticleBulletinClassification(Base):
    """Cached LLM classification of an article for bulletin generation, keyed by a
    hash of the top-level category set in effect when it was classified — so
    editing categories invalidates stale rows instead of silently reusing them."""
    __tablename__ = "article_bulletin_classifications"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    category_set_hash = Column(String, nullable=False, index=True)
    top_category = Column(String, nullable=False)
    subcategory = Column(String, nullable=False)   # LLM-generated dynamic label
    article_type = Column(String, nullable=False)  # "haber" | "haber_detayi" | "yorum"
    model_used = Column(String)
    created_at = Column(UTCDateTime(), server_default=func.now())

    # Relationships
    article = relationship("Article")

    __table_args__ = (
        UniqueConstraint("article_id", "category_set_hash", name="uq_bulletin_classification_article_hash"),
    )


class User(Base):
    """Application user model."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # "admin" or "user"
    is_active = Column(Boolean, default=True)
    created_at = Column(UTCDateTime(), server_default=func.now())
