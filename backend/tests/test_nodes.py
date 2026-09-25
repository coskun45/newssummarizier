"""
Tests for app/agents/nodes.py (LangGraph pipeline nodes).
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.agents import nodes
from app.db import crud, models
from tests.conftest import _make_article, _make_feed, _make_topic


def test_rss_fetcher_node_dedupes_same_url_within_one_poll(monkeypatch, db_session):
    """Regression: a feed that lists the same article URL twice in a single poll
    (e.g. a multi-category aggregate feed) made rss_fetcher_node pass both copies
    through, since it only checked the DB — not the batch itself — for
    duplicates. article_processor_node then crashed inserting the second copy
    with a UniqueViolation on articles.url."""
    monkeypatch.setattr(nodes, "SessionLocal", sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    feed = _make_feed(db_session)

    duplicate_entry = {
        "url": "https://example.com/dup-article", "title": "Duplicate", "author": None,
        "published_at": None, "raw_content": None, "image_url": None,
    }

    async def fake_fetch_rss_feed(feed_url):
        return [dict(duplicate_entry), dict(duplicate_entry)]

    monkeypatch.setattr(nodes, "fetch_rss_feed", fake_fetch_rss_feed)

    state = {"feed_id": feed.id, "feed_url": feed.url, "errors": []}

    out = asyncio.run(nodes.rss_fetcher_node(state))

    assert out["total_articles"] == 1
    urls = [a["url"] for a in out["rss_articles"]]
    assert urls == ["https://example.com/dup-article"]


# ---------------------------------------------------------------------------
# Full feed pipeline (rss_fetcher -> article processing) with OpenAI/scraping stubbed
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_env(monkeypatch, db_session):
    """Point the pipeline at the test DB and stub RSS, scraping and OpenAI. Stubs are set on both
    the node module and summary_service, since either may own the per-article steps."""
    from app.services import summary_service
    from app.tasks import background

    test_sessions = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    for module in (nodes, summary_service, background):
        monkeypatch.setattr(module, "SessionLocal", test_sessions)

    env = SimpleNamespace(rss_entries=[], categorization={
        "importance": "important", "priority": "high", "topics": [],
    }, on_categorize=None)

    async def fake_fetch_rss_feed(feed_url):
        return [dict(e) for e in env.rss_entries]

    async def fake_extract(url):
        return "page body", None, None

    async def fake_categorize(title):
        if env.on_categorize:
            env.on_categorize()
        return env.categorization

    async def fake_summary(title, content, summary_type="standard", source=None, author_hint=None):
        return {"summary_text": f"{summary_type} summary", "model_used": "m", "tokens_used": 1,
                "cost": 0.0, "author": None, "structured": True}

    monkeypatch.setattr(nodes, "fetch_rss_feed", fake_fetch_rss_feed)
    for module in (nodes, summary_service):
        monkeypatch.setattr(module, "extract_article_content", fake_extract, raising=False)
        monkeypatch.setattr(module, "categorize_and_prioritize_article", fake_categorize, raising=False)
        monkeypatch.setattr(module, "generate_summary", fake_summary, raising=False)
    return env


def _rss_entry(n):
    return {"url": f"https://example.com/news-{n}", "title": f"Haber {n}", "author": None,
            "published_at": None, "raw_content": "rss body", "image_url": None}


def test_pipeline_duplicate_topic_from_llm_keeps_article_labelled(pipeline_env, db_session):
    """Regression (#23): the same topic twice (or a non-dict topic) in the classification answer hit
    the article_topics primary key, and the article fell into the Error group without a priority."""
    from app.tasks import background

    feed = _make_feed(db_session)
    _make_topic(db_session, "NATO")
    pipeline_env.rss_entries = [_rss_entry(1)]
    pipeline_env.categorization = {"importance": "important", "priority": "high", "topics": [
        {"name": "NATO", "confidence": 0.9}, {"name": "NATO", "confidence": 0.8}, "NATO",
    ]}

    asyncio.run(background.process_feed_async(feed.id))

    db_session.expire_all()
    article = crud.get_article_by_url(db_session, "https://example.com/news-1")
    assert (article.status, article.priority) == ("summarized", "high")
    assert [t.topic.name for t in article.topics] == ["NATO"]


def test_pipeline_processes_more_new_articles_than_the_recursion_limit(pipeline_env, db_session, monkeypatch):
    """Regression (#30): the graph took one step per article, so a refresh with more new articles
    than GRAPH_RECURSION_LIMIT raised GraphRecursionError and left the rest unprocessed."""
    from app.core.config import settings
    from app.tasks import background

    monkeypatch.setattr(settings, "graph_recursion_limit", 5)
    feed = _make_feed(db_session)
    pipeline_env.rss_entries = [_rss_entry(n) for n in range(12)]

    asyncio.run(background.process_feed_async(feed.id))

    db_session.expire_all()
    assert background.get_job_status(feed.id)["status"] == "done"
    statuses = [a.status for a in db_session.query(models.Article).filter_by(feed_id=feed.id)]
    assert statuses == ["summarized"] * 12


def test_new_article_count_only_counts_this_feeds_new_articles(pipeline_env, db_session):
    """Regression (#26): the "X yeni makale" count was the change in the *global* article count,
    so articles another job added (or the user deleted) meanwhile skewed it."""
    from app.tasks import background

    feed = _make_feed(db_session)
    other_feed = _make_feed(db_session, url="https://example.com/other-feed")
    doomed = _make_article(db_session, other_feed.id)
    pipeline_env.rss_entries = [_rss_entry(1), _rss_entry(2)]
    calls = iter(range(100))

    def meanwhile():
        n = next(calls)
        if n == 0:  # another feed's job lands three articles while this one runs
            for i in range(3):
                _make_article(db_session, other_feed.id)
        elif n == 1:  # ...and the user deletes one
            crud.delete_article(db_session, doomed.id)

    pipeline_env.on_categorize = meanwhile

    asyncio.run(background.process_feed_async(feed.id))

    status = background.get_job_status(feed.id)
    assert status["status"] == "done"
    assert status["new_articles"] == 2
