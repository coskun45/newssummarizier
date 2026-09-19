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


def test_reprocess_without_any_summary_is_failed_not_summarized(reprocess_env, monkeypatch, db_session):
    """Regression: an article was marked "summarized" even when no summary was created."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="body")
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "low", "topics": []})

    async def broken_summary(**kwargs):
        raise RuntimeError("openai down")

    monkeypatch.setattr(reprocess_env, "generate_summary", broken_summary)

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["status"] == "failed" and result["success"] is False
    db_session.expire_all()
    assert article.status == "failed"
    assert article.priority == "low"  # it did get a label, so it leaves the Error group


def test_reprocess_success_sends_article_back_to_unread(reprocess_env, monkeypatch, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="body", is_read=True)
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "high", "topics": []})

    asyncio.run(reprocess_env.process_article_by_id(article.id))

    db_session.expire_all()
    assert article.is_read is False and article.status == "summarized"


def test_reprocess_failure_leaves_read_state_alone(reprocess_env, monkeypatch, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="body", is_read=True)
    _set_categorization(monkeypatch, reprocess_env, error=RuntimeError("openai down"))

    asyncio.run(reprocess_env.process_article_by_id(article.id))

    db_session.expire_all()
    assert article.is_read is True


def test_fix_summarized_status_only_touches_wrongly_marked_articles(db_session):
    feed = _make_feed(db_session)
    good = _make_article(db_session, feed.id, status="summarized", importance="important", priority="high")
    _make_summary(db_session, good.id)
    no_summary = _make_article(db_session, feed.id, status="summarized", importance="important", priority="med")
    unlabelled = _make_article(db_session, feed.id, status="summarized")
    _make_summary(db_session, unlabelled.id)
    filtered = _make_article(db_session, feed.id, status="filtered", importance="unimportant")

    assert crud.fix_summarized_status(db_session) == 2
    assert crud.fix_summarized_status(db_session) == 0  # idempotent

    db_session.expire_all()
    assert good.status == "summarized"
    assert no_summary.status == "failed"
    assert unlabelled.status == "failed"
    assert filtered.status == "filtered"


def test_pipeline_node_categorization_failure_is_failed_not_summarized(monkeypatch, db_session):
    """Regression: the feed pipeline swallowed a failed categorization, still generated
    summaries and marked the unlabelled article "summarized"."""
    from sqlalchemy.orm import sessionmaker
    from app.agents import nodes

    monkeypatch.setattr(nodes, "SessionLocal", sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    feed = _make_feed(db_session)

    async def fake_extract(url):
        return "some body text", None, None

    async def failing_categorize(title):
        raise RuntimeError("openai down")

    summary_calls = []

    async def fake_summary(**kwargs):
        summary_calls.append(kwargs)
        return {"summary_text": "s", "model_used": "m", "tokens_used": 1, "cost": 0.0}

    monkeypatch.setattr(nodes, "extract_article_content", fake_extract)
    monkeypatch.setattr(nodes, "categorize_and_prioritize_article", failing_categorize)
    monkeypatch.setattr(nodes, "generate_summary", fake_summary)

    state = {
        "feed_id": feed.id, "feed_url": feed.url, "current_article_index": 0,
        "rss_articles": [{"url": "https://example.com/x", "title": "T", "raw_content": "raw"}],
        "processed_articles": [], "errors": [], "total_cost": 0.0, "should_continue": True,
    }

    out = asyncio.run(nodes.article_processor_node(state))

    db_session.expire_all()
    article = crud.get_article_by_url(db_session, "https://example.com/x")
    assert article.status == "failed"
    assert article.priority is None and article.importance is None
    assert summary_calls == []  # no money spent summarizing an unlabelled article
    assert out["current_article_index"] == 1 and out["should_continue"] is False
    assert crud.get_error_article_ids(db_session) == [article.id]


def test_reprocess_recovers_labelled_failed_article(reprocess_env, monkeypatch, db_session):
    """A labelled article stuck on "failed" (no summary) gets its summaries on a retry and leaves the Error group."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", importance="important",
                            priority="high", cleaned_content="body", is_read=True)
    _set_categorization(monkeypatch, reprocess_env,
                        {"importance": "important", "priority": "high", "topics": []})
    assert crud.get_error_article_ids(db_session) == [article.id]

    result = asyncio.run(reprocess_env.process_article_by_id(article.id))

    assert result["success"] is True
    db_session.expire_all()
    assert article.status == "summarized" and article.is_read is False
    assert crud.get_error_article_ids(db_session) == []


# ---------------------------------------------------------------------------
# categorize_and_prioritize_article / generate_summary keep their pre-Playground contract
# (the Playground shares their _run_* helpers, so the public return shape must not drift).
# ---------------------------------------------------------------------------

def _fake_openai(monkeypatch, db_session, content):
    from types import SimpleNamespace
    from sqlalchemy.orm import sessionmaker

    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=SimpleNamespace(completion_tokens=5),
        )

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(summary_service, "get_openai_client", lambda: fake)
    monkeypatch.setattr(summary_service, "SessionLocal",
                        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    return calls


def test_categorize_returns_only_importance_priority_topics(monkeypatch, db_session):
    _make_topic(db_session, "NATO", description="Bündnis")
    calls = _fake_openai(monkeypatch, db_session,
                         '```json' + chr(10) + '{"importance": "important", "priority": "med", "topics": [{"name": "NATO", "confidence": 0.8}]}' + chr(10) + '```')

    result = asyncio.run(summary_service.categorize_and_prioritize_article("NATO-Gipfel"))

    assert result == {"importance": "important", "priority": "med",
                      "topics": [{"name": "NATO", "confidence": 0.8}]}
    assert calls[0]["model"] == settings.default_model
    assert "- NATO: Bündnis" in calls[0]["messages"][0]["content"]


def test_categorize_invalid_json_twice_raises(monkeypatch, db_session):
    from app.core.exceptions import TopicCategorizationError

    calls = _fake_openai(monkeypatch, db_session, "definitely not json")

    with pytest.raises(TopicCategorizationError):
        asyncio.run(summary_service.categorize_and_prioritize_article("Titel"))
    assert len(calls) == 2


def test_generate_summary_returns_persistable_fields(monkeypatch, db_session):
    calls = _fake_openai(monkeypatch, db_session, "  Kurz und knapp.  ")

    result = asyncio.run(summary_service.generate_summary("Titel", "Inhalt", "detailed"))

    assert set(result) == {"summary_text", "model_used", "tokens_used", "cost"}
    assert result["summary_text"] == "Kurz und knapp."
    assert result["model_used"] == settings.detailed_model
    assert calls[0]["max_completion_tokens"] == settings.max_tokens_output_detailed
    assert summary_service.DEFAULT_SUMMARY_INSTRUCTIONS["detailed"] in calls[0]["messages"][1]["content"]


def test_generate_summary_empty_response_and_bad_type_raise(monkeypatch, db_session):
    from app.core.exceptions import SummarizationError

    _fake_openai(monkeypatch, db_session, None)
    with pytest.raises(SummarizationError):
        asyncio.run(summary_service.generate_summary("Titel", "Inhalt", "brief"))
    with pytest.raises(SummarizationError):
        asyncio.run(summary_service.generate_summary("Titel", "Inhalt", "huge"))
