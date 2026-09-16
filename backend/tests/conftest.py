"""
Shared pytest fixtures: an isolated in-memory SQLite DB per test, wired into
the FastAPI app via a `get_db` dependency override, plus a pre-created user
and its auth headers for protected routes.

The `client` fixture never enters the app's lifespan (no `with TestClient(...)`),
so `init_db()`/`seed_database()`/the APScheduler never touch the real
`news_summary.db` or start background jobs during tests.
"""
import itertools

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.database import Base, get_db
from app.db import crud, models
from app.core.security import hash_password, create_access_token
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def test_user(db_session):
    return crud.create_user(
        db=db_session,
        email="tester@example.com",
        hashed_password=hash_password("testpass123"),
        role="user",
    )


@pytest.fixture()
def auth_headers(test_user):
    token = create_access_token(
        {"sub": str(test_user.id), "email": test_user.email, "role": test_user.role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_user(db_session):
    return crud.create_user(
        db=db_session,
        email="admin@example.com",
        hashed_password=hash_password("adminpass123"),
        role="admin",
    )


@pytest.fixture()
def admin_headers(admin_user):
    token = create_access_token(
        {"sub": str(admin_user.id), "email": admin_user.email, "role": admin_user.role}
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# ORM row-builder helpers shared by test_articles.py / test_rss.py /
# test_summaries.py / test_topics.py. Build rows directly via the ORM (never
# through crud.*) to keep fixture state independent of the code under test.
# ---------------------------------------------------------------------------

def _make_feed(db_session, url="https://example.com/feed", *, title="Test Feed",
                description=None, is_active=True):
    feed = models.Feed(url=url, title=title, description=description, is_active=is_active)
    db_session.add(feed)
    db_session.commit()
    db_session.refresh(feed)
    return feed


_article_url_counter = itertools.count()


def _make_article(db_session, feed_id, *, title="Test Article", url=None, priority=None,
                   importance=None, is_read=False, is_starred=False, status="pending",
                   published_at=None, raw_content=None, cleaned_content=None, author=None,
                   image_url=None):
    article = models.Article(
        feed_id=feed_id,
        url=url or f"https://example.com/article-{next(_article_url_counter)}",
        title=title,
        author=author,
        published_at=published_at,
        raw_content=raw_content,
        cleaned_content=cleaned_content,
        status=status,
        importance=importance,
        priority=priority,
        is_read=is_read,
        is_starred=is_starred,
        image_url=image_url,
    )
    db_session.add(article)
    db_session.commit()
    db_session.refresh(article)
    return article


def _make_topic(db_session, name="Test Topic", *, description=None, color=None):
    topic = models.Topic(name=name, description=description, color=color)
    db_session.add(topic)
    db_session.commit()
    db_session.refresh(topic)
    return topic


def _make_article_topic(db_session, article_id, topic_id, confidence=1.0):
    link = models.ArticleTopic(article_id=article_id, topic_id=topic_id, confidence=confidence)
    db_session.add(link)
    db_session.commit()
    db_session.refresh(link)
    return link


def _make_summary(db_session, article_id, *, summary_type="standard",
                   summary_text="Test summary", model_used="gpt-4o-mini",
                   tokens_used=100, cost=0.01):
    summary = models.Summary(
        article_id=article_id,
        summary_text=summary_text,
        summary_type=summary_type,
        model_used=model_used,
        tokens_used=tokens_used,
        cost=cost,
    )
    db_session.add(summary)
    db_session.commit()
    db_session.refresh(summary)
    return summary
