"""
Tests for app/agents/nodes.py (LangGraph pipeline nodes).
"""
import asyncio

from sqlalchemy.orm import sessionmaker

from app.agents import nodes
from tests.conftest import _make_feed


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
