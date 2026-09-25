"""
Regression tests for DB connection-pool exhaustion ("QueuePool limit of size 5 overflow 10
reached") that locked every user out, login included, until the backend was restarted.

Three things combined into a self-sustaining jam:
1. The feed pipeline / reprocess / scheduler kept a transaction open (so a pooled connection
   checked out, "idle in transaction") across every scrape and OpenAI `await` — the scheduler
   for its whole hourly run. `crud.create_log()`'s `db.refresh()` alone re-opens one.
2. `async def` routes ran synchronous DB calls on the event loop: once the pool was full each
   such request froze the whole loop for the 30s pool timeout, so the coroutines holding
   connections could never resume to release them.
3. The engine had no safety net (no pre-ping, no server-side idle/statement timeouts).
4. The trigger: a dashboard refresh started a pipeline for every feed (40+) in parallel.
"""
import asyncio
import inspect

import pytest
from fastapi.routing import APIRoute
from sqlalchemy.orm import sessionmaker

from app.db import crud
from app.db import database as db_module
from app.db.database import get_db
from app.main import app
from tests.conftest import _make_article, _make_feed


@pytest.fixture
def session_spy(db_session):
    """A SessionLocal replacement bound to the test DB that records every session it opens.

    Uses SQLAlchemy's default expire_on_commit=True like production, so attribute access after
    a commit re-opens a transaction exactly as it does against PostgreSQL.
    """
    factory = sessionmaker(autocommit=False, autoflush=False, bind=db_session.get_bind())
    sessions = []

    def make_session():
        session = factory()
        sessions.append(session)
        return session

    violations = []

    def check(where):
        # Recorded, not raised: the code under test swallows exceptions from these stubs.
        if any(s.in_transaction() for s in sessions):
            violations.append(where)

    make_session.check = check
    make_session.violations = violations
    return make_session


# --------------------------------------------------------------------------- engine safety net

def test_postgres_engine_has_pool_safety_net():
    kwargs = db_module._engine_kwargs("postgresql+psycopg2://u:p@db:5432/bulten")

    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] > 0
    assert kwargs["pool_timeout"] <= 10  # fail fast instead of freezing a worker for 30s
    options = kwargs["connect_args"]["options"]
    assert "idle_in_transaction_session_timeout=" in options
    assert "statement_timeout=" in options


def test_sqlite_engine_kwargs_unchanged():
    kwargs = db_module._engine_kwargs("sqlite://")
    assert kwargs == {"connect_args": {"check_same_thread": False}}


# --------------------------------------------------------------------------- routes

def _endpoint_uses_db(endpoint) -> bool:
    # The endpoint's own `db: Session = Depends(get_db)` — not the router-level JWT dependency,
    # which FastAPI already runs in the threadpool.
    return any(getattr(p.default, "dependency", None) is get_db
               for p in inspect.signature(endpoint).parameters.values())


def test_db_routes_without_await_are_sync_so_they_run_in_the_threadpool():
    """An `async def` route runs on the event loop, so its synchronous DB calls block the loop —
    for up to the whole pool timeout when the pool is exhausted. Routes that don't await
    anything must be plain `def` so FastAPI runs them in its threadpool."""
    offenders = [
        f"{sorted(route.methods)} {route.path} ({route.endpoint.__name__})"
        for route in app.routes
        if isinstance(route, APIRoute)
        and inspect.iscoroutinefunction(route.endpoint)
        and _endpoint_uses_db(route.endpoint)
        and "await " not in inspect.getsource(route.endpoint)
    ]
    assert offenders == []


# --------------------------------------------------------------------------- feed pipeline

def test_article_processor_node_releases_connection_during_awaits(monkeypatch, db_session, session_spy):
    from app.agents import nodes

    monkeypatch.setattr(nodes, "SessionLocal", session_spy)
    feed = _make_feed(db_session)

    async def fake_extract(url):
        session_spy.check("scraping")
        return "some body text", None, None

    async def fake_categorize(title):
        session_spy.check("classification")
        return {"importance": "important", "priority": "high", "topics": []}

    async def fake_summary(**kwargs):
        session_spy.check("summarization")
        return {"summary_text": "s", "model_used": "m", "tokens_used": 1, "cost": 0.0}

    monkeypatch.setattr(nodes, "extract_article_content", fake_extract)
    monkeypatch.setattr(nodes, "categorize_and_prioritize_article", fake_categorize)
    monkeypatch.setattr(nodes, "generate_summary", fake_summary)

    state = {
        "feed_id": feed.id, "feed_url": feed.url, "current_article_index": 0,
        "rss_articles": [{"url": "https://example.com/x", "title": "T", "raw_content": "raw"}],
        "processed_articles": [], "errors": [], "total_cost": 0.0, "should_continue": True,
    }

    out = asyncio.run(nodes.article_processor_node(state))

    assert session_spy.violations == []
    assert "errors" not in out
    db_session.expire_all()
    assert crud.get_article_by_url(db_session, "https://example.com/x").status == "summarized"


def test_process_feed_does_not_hold_connection_while_workflow_runs(monkeypatch, db_session, session_spy):
    from app.tasks import background

    monkeypatch.setattr(background, "SessionLocal", session_spy)
    feed = _make_feed(db_session)
    seen = {}

    class FakeWorkflow:
        async def ainvoke(self, state, config=None):
            session_spy.check("the LangGraph workflow")
            seen["feed_url"] = state["feed_url"]
            return {"processed_articles": [], "total_cost": 0.0, "errors": []}

    monkeypatch.setattr(background, "get_workflow", lambda: FakeWorkflow())

    asyncio.run(background.process_feed_async(feed.id))

    assert session_spy.violations == []
    assert background.get_job_status(feed.id)["status"] == "done"
    assert seen["feed_url"] == feed.url


def test_reprocess_does_not_hold_connection_during_awaits(monkeypatch, db_session, session_spy):
    from app.services import summary_service

    monkeypatch.setattr(summary_service, "SessionLocal", session_spy)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed")

    async def fake_extract(url):
        session_spy.check("scraping")
        return "body", None, None

    async def fake_categorize(title):
        session_spy.check("classification")
        return {"importance": "important", "priority": "high", "topics": []}

    async def fake_summary(**kwargs):
        session_spy.check("summarization")
        return {"summary_text": "s", "model_used": "m", "tokens_used": 1, "cost": 0.0}

    monkeypatch.setattr(summary_service, "extract_article_content", fake_extract)
    monkeypatch.setattr(summary_service, "categorize_and_prioritize_article", fake_categorize)
    monkeypatch.setattr(summary_service, "generate_summary", fake_summary)

    result = asyncio.run(summary_service.process_article_by_id(article.id))

    assert session_spy.violations == []
    assert result["success"] is True


# --------------------------------------------------------------------------- scheduler

def test_scheduler_does_not_hold_connection_while_processing_feeds(monkeypatch, db_session, session_spy):
    from app.tasks import background, scheduler

    monkeypatch.setattr(db_module, "SessionLocal", session_spy)
    feed = _make_feed(db_session)
    processed = []

    async def fake_process_feed_task(feed_id):
        session_spy.check("feed processing")
        processed.append(feed_id)

    monkeypatch.setattr(background, "process_feed_task", fake_process_feed_task)

    asyncio.run(scheduler._process_all_feeds())

    assert session_spy.violations == []
    assert processed == [feed.id]


# --------------------------------------------------------------------------- feed concurrency

def test_feed_refreshes_run_one_at_a_time(monkeypatch):
    """Root trigger: "refresh" on the dashboard POSTs /feeds/{id}/refresh for every feed (40+ in
    production) at once, and each background task started its own LangGraph run immediately —
    40 concurrent pipelines x 2-3 connections each against a 15-connection pool."""
    from app.tasks import background

    running = 0
    peak = 0

    async def fake_process_feed_async(feed_id):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1

    monkeypatch.setattr(background, "process_feed_async", fake_process_feed_async)

    async def refresh_all():
        await asyncio.gather(*(background.process_feed_task(feed_id) for feed_id in range(1, 11)))

    asyncio.run(refresh_all())

    assert peak == 1


def test_feed_already_queued_is_not_queued_twice(monkeypatch):
    """A second refresh click (or the hourly run) while a feed is still queued/running must not
    start another pipeline for it."""
    from app.tasks import background

    calls = []

    async def fake_process_feed_async(feed_id):
        calls.append(feed_id)
        await asyncio.sleep(0.01)

    monkeypatch.setattr(background, "process_feed_async", fake_process_feed_async)

    async def double_click():
        await asyncio.gather(background.process_feed_task(7), background.process_feed_task(7))

    asyncio.run(double_click())

    assert calls == [7]
