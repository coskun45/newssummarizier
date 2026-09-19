"""
Tests for app/services/summary_service.py — OpenAI client construction.
"""
import asyncio

import pytest

import app.services.summary_service as summary_service
from app.core.config import settings
from app.db import crud
from tests.conftest import _make_feed, _make_article, _make_topic, _make_article_topic, _make_summary


def test_get_openai_client_sets_bounded_timeout(monkeypatch):
    captured_kwargs = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr(summary_service, "AsyncOpenAI", _FakeAsyncOpenAI)
    monkeypatch.setattr(summary_service, "_client", None)

    summary_service.get_openai_client()

    assert captured_kwargs.get("timeout") == settings.openai_timeout_seconds
    assert captured_kwargs["timeout"] is not None


# ---------------------------------------------------------------------------
# process_article_by_id — re-processing of "Error" articles
# ---------------------------------------------------------------------------

@pytest.fixture
def reprocess_env(monkeypatch, db_session):
    """Point summary_service at the in-memory test DB and stub out OpenAI/scraping."""
    from sqlalchemy.orm import sessionmaker
    from app.services import summary_service

    monkeypatch.setattr(summary_service, "SessionLocal",
                        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))

    async def fake_summary(title, content, summary_type="standard"):
        return {"summary_text": f"{summary_type} summary", "model_used": "m", "tokens_used": 1, "cost": 0.0}

    monkeypatch.setattr(summary_service, "generate_summary", fake_summary)
    return summary_service


def _set_categorization(monkeypatch, summary_service, result=None, error=None):
    async def fake(title):
        if error:
            raise error
        return result

    monkeypatch.setattr(summary_service, "categorize_and_prioritize_article", fake)


def test_reprocess_assigns_priority_and_replaces_old_summaries(reprocess_env, monkeypatch, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="body")
    topic = _make_topic(db_session, "Politik")
    _make_article_topic(db_session, article.id, topic.id)
    _make_summary(db_session, article.id, summary_type="brief", summary_text="OLD")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "high",
                         "topics": [{"name": "Politik", "confidence": 0.9}]})

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is True
    db_session.expire_all()
    assert (article.status, article.importance, article.priority) == ("summarized", "important", "high")
    texts = [s.summary_text for s in article.summaries]
    assert "OLD" not in texts and len(texts) == len(set(s.summary_type for s in article.summaries))
    assert len(article.topics) == 1  # no duplicate-PK collision on the second run


def test_reprocess_categorization_failure_stays_in_error_group(reprocess_env, monkeypatch, db_session):
    """Regression: a failed categorization used to leave the article `summarized` with no
    label, so it could never be told apart from a healthy one."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", cleaned_content="body")
    _set_categorization(monkeypatch, reprocess_env, error=RuntimeError("openai down"))

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is False
    db_session.expire_all()
    assert article.status == "failed"
    assert article.priority is None and article.importance is None
    assert crud.get_error_article_ids(db_session) == [article.id]


def test_reprocess_important_without_priority_counts_as_failure(reprocess_env, monkeypatch, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", cleaned_content="body")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": None, "topics": []})

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is False
    db_session.expire_all()
    assert article.status == "failed"


def test_reprocess_unimportant_leaves_error_group_as_filtered(reprocess_env, monkeypatch, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", cleaned_content="body")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "unimportant", "priority": None, "topics": []})

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result == {"article_id": article.id, "status": "filtered", "cost": 0.0, "success": True}
    assert crud.get_error_article_ids(db_session) == []


def test_reprocess_task_tracks_progress_and_failures(monkeypatch):
    from app.tasks import background
    from app.services import summary_service

    async def fake_process(article_id):
        if article_id == 2:
            raise RuntimeError("boom")
        return {"success": article_id != 3}

    monkeypatch.setattr(summary_service, "process_article_by_id", fake_process)
    monkeypatch.setattr(crud, "update_article_status", lambda *a, **k: None)
    background._reprocess_status.update({"status": "idle", "total": 0, "done": 0, "failed": 0})
    background.register_reprocess(3)

    asyncio.run(background.reprocess_articles_task([1, 2, 3]))

    assert background.get_reprocess_status() == {"status": "done", "total": 3, "done": 3, "failed": 2}


def test_reprocess_failed_retry_keeps_existing_topics_and_summaries(reprocess_env, monkeypatch, db_session):
    """Regression: old topics/summaries were deleted *before* re-classification, so a retry
    that failed (OpenAI down) destroyed the content it was supposed to repair."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="summarized", cleaned_content="body")
    topic = _make_topic(db_session, "Politik")
    _make_article_topic(db_session, article.id, topic.id)
    _make_summary(db_session, article.id, summary_text="KEEP ME")
    _set_categorization(monkeypatch, reprocess_env, error=RuntimeError("openai down"))

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is False
    db_session.expire_all()
    assert [s.summary_text for s in article.summaries] == ["KEEP ME"]
    assert len(article.topics) == 1


def test_reprocess_duplicate_topic_from_llm_does_not_break_the_run(reprocess_env, monkeypatch, db_session):
    """Regression: the same topic twice hit the (article_id, topic_id) PK; the un-rolled-back
    session then made the error handler itself raise instead of returning a result."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="body")
    _make_topic(db_session, "Politik")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "med",
                         "topics": [{"name": "Politik", "confidence": 0.9},
                                    {"name": "Politik", "confidence": 0.8}]})

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is True
    db_session.expire_all()
    assert len(article.topics) == 1


def test_failed_categorization_write_error_is_rolled_back(reprocess_env, monkeypatch, db_session):
    """A DB error inside the categorization block must be rolled back so the failure
    handler can still log and return success=False."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", cleaned_content="body")
    _make_topic(db_session, "Politik")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "high",
                         "topics": [{"name": "Politik", "confidence": 0.9}]})

    def boom(*a, **k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(crud, "add_article_topic", boom)

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is False
    db_session.expire_all()
    assert article.status == "failed" and article.priority is None


def test_reset_stale_pending_articles_makes_them_retryable(db_session):
    feed = _make_feed(db_session)
    stuck = _make_article(db_session, feed.id, status="pending")
    fine = _make_article(db_session, feed.id, status="summarized", priority="high")

    assert crud.get_error_article_ids(db_session) == []  # pending is invisible to the Error group
    assert crud.reset_stale_pending_articles(db_session) == 1

    db_session.expire_all()
    assert stuck.status == "failed" and fine.status == "summarized"
    assert crud.get_error_article_ids(db_session) == [stuck.id]


def test_reprocess_task_cancellation_does_not_strand_articles(monkeypatch):
    from app.tasks import background
    from app.services import summary_service

    marked = []

    async def fake_process(article_id):
        if article_id == 2:
            raise asyncio.CancelledError()
        return {"success": True}

    monkeypatch.setattr(summary_service, "process_article_by_id", fake_process)
    monkeypatch.setattr(crud, "update_article_status", lambda db, aid, st: marked.append((aid, st)))
    background._reprocess_status.update({"status": "idle", "total": 0, "done": 0, "failed": 0})
    background.register_reprocess(3)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background.reprocess_articles_task([1, 2, 3]))

    # articles 2 and 3 were never finished -> back to "failed" (visible in Error), not "pending"
    assert marked == [(2, "failed"), (3, "failed")]
    assert background.get_reprocess_status() == {"status": "done", "total": 3, "done": 3, "failed": 2}
