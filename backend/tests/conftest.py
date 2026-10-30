"""
Shared pytest fixtures: an isolated in-memory SQLite DB per test, wired into
the FastAPI app via a `get_db` dependency override, plus a pre-created user
and its auth headers for protected routes.

The `client` fixture never enters the app's lifespan (no `with TestClient(...)`),
so `init_db()`/`seed_database()`/the APScheduler never touch the real
PostgreSQL DB or start background jobs during tests.
"""
import itertools

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.db.database import Base, get_db
from app.db import crud, models
from app.core.security import hash_password, create_access_token
from app.main import app


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    """Tests never do real DNS lookups: the SSRF guard resolves hosts through this fake.
    IP literals resolve to themselves, `localhost` and `*.internal` to private addresses,
    everything else to a public one."""
    import ipaddress
    from app.core import url_safety

    def resolve(hostname):
        try:
            return {str(ipaddress.ip_address(hostname))}
        except ValueError:
            pass
        if hostname == "localhost":
            return {"127.0.0.1"}
        if hostname.endswith(".internal"):
            return {"10.0.0.5"}
        return {"93.184.216.34"}

    monkeypatch.setattr(url_safety, "_resolve_host", resolve, raising=False)


class FakePages:
    """Stand-in for the page scraper: `pages[url] = (content, author, image_url)`; any other URL
    yields nothing, as a page without extractable text does. `calls` lists the fetched URLs."""

    def __init__(self):
        self.pages = {}
        self.calls = []

    async def extract(self, url):
        self.calls.append(url)
        return self.pages.get(url, (None, None, None))


@pytest.fixture(autouse=True)
def fake_pages(monkeypatch):
    """Tests never fetch real article pages: every on-demand fetch goes through this fake."""
    from app.services import summary_service

    pages = FakePages()
    monkeypatch.setattr(summary_service, "extract_article_content", pages.extract)
    return pages


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite ignores foreign keys unless asked; PostgreSQL (prod) always enforces them.
    # Without this, a delete that violates an FK passes here and 500s in production.
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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


def _make_bulletin_classification(db_session, article_id, *, category_set_hash="hash",
                                   top_category="AVRUPA", subcategory="Genel",
                                   article_type="haber"):
    row = models.ArticleBulletinClassification(
        article_id=article_id,
        category_set_hash=category_set_hash,
        top_category=top_category,
        subcategory=subcategory,
        article_type=article_type,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Asistan (analysis chat) fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def agent_db(monkeypatch, db_session):
    """Point the Asistan's own sessions (agent nodes, tools, chat_service, the cost booking in
    summary_service, the embedding backfill) at the in-memory test DB, and create the chat_*
    views the SQL tool reads."""
    from sqlalchemy.orm import sessionmaker
    from app.agents.analysis import nodes, tools
    from app.db.database import create_chat_views
    from app.services import chat_service, summary_service
    from app.tasks import background

    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    for module in (nodes, tools, chat_service, summary_service, background):
        monkeypatch.setattr(module, "SessionLocal", factory)
    create_chat_views(db_session.get_bind())
    return factory


class FakeAgentLLM:
    """Stand-in for summary_service.run_agent_llm / stream_agent_llm. Script answers per agent
    stage with `script(purpose, *answers)`; an answer is a dict (JSON-mode content), a string
    (plain content) or `tool_call(name, **arguments)`. A stage without a scripted answer gets a
    sensible default, so a test scripts only what it is about. `calls` records every call."""

    def __init__(self):
        self.answers = {}
        self.calls = []
        self.report = "Rapor: sonuç [#1]."
        self.cost_per_call = 0.0

    def script(self, purpose, *answers):
        self.answers.setdefault(purpose, []).extend(answers)

    @staticmethod
    def tool_call(name, **arguments):
        import json
        return {"tool_calls": [{"id": f"call_{name}_{next(_tool_call_ids)}", "name": name,
                                "arguments": json.dumps(arguments)}]}

    _DEFAULTS = {
        "understand": {"restatement": "Anlaşılan amaç", "analysis_type": "distribution", "open_questions": []},
        "plan": {"steps": [{"goal": "Önem seviyelerini say", "tool": "sql"}]},
        "execute": "Adım bulgusu.",
        "reflect": {"decision": "continue"},
        "relevance": {"irrelevant": []},  # the semantic search's relevance check keeps every hit
    }

    async def run(self, messages, model, max_tokens, *, purpose, json_mode=False, tools=None, temperature=0.2):
        import json
        self.calls.append({"purpose": purpose, "messages": messages, "tools": tools})
        queue = self.answers.get(purpose) or []
        answer = queue.pop(0) if queue else self._DEFAULTS[purpose]
        if isinstance(answer, dict) and "tool_calls" in answer:
            return {"content": "", "tool_calls": answer["tool_calls"], "finish_reason": "tool_calls",
                    "cost": self.cost_per_call, "purpose": purpose}
        content = json.dumps(answer, ensure_ascii=False) if isinstance(answer, dict) else answer
        return {"content": content, "tool_calls": [], "finish_reason": "stop", "cost": self.cost_per_call,
                "purpose": purpose}

    async def stream(self, messages, model, max_tokens, *, purpose, temperature=0.3):
        self.calls.append({"purpose": purpose, "messages": messages, "tools": None})
        for piece in (self.report[: len(self.report) // 2], self.report[len(self.report) // 2:]):
            yield ("token", piece)
        yield ("cost", self.cost_per_call)


_tool_call_ids = itertools.count(1)


@pytest.fixture()
def fake_agent_llm(monkeypatch):
    from app.services import summary_service

    fake = FakeAgentLLM()
    monkeypatch.setattr(summary_service, "run_agent_llm", fake.run)
    monkeypatch.setattr(summary_service, "stream_agent_llm", fake.stream)
    return fake
