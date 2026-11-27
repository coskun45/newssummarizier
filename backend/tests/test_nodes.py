"""
Tests for app/agents/nodes.py (LangGraph pipeline nodes).
"""
import asyncio
from datetime import datetime, timedelta, timezone

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


def _run_fetcher_with(monkeypatch, db_session, entries):
    """URLs rss_fetcher_node passes on for a feed listing `entries` (runs against the test DB)."""
    monkeypatch.setattr(nodes, "SessionLocal", sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))

    async def fake_fetch_rss_feed(feed_url):
        return [dict(e) for e in entries]

    monkeypatch.setattr(nodes, "fetch_rss_feed", fake_fetch_rss_feed)
    state = {"feed_id": 1, "feed_url": "https://example.com/feed", "errors": []}
    out = asyncio.run(nodes.rss_fetcher_node(state))
    return [a["url"] for a in out["rss_articles"]]


def _dated_entry(url, published_at):
    return {"url": url, "title": url, "author": None, "published_at": published_at,
            "raw_content": None, "image_url": None}


def test_rss_fetcher_node_skips_entries_older_than_max_age(monkeypatch, db_session):
    """Regression: DW's rss-de-all feed also lists months-old background pieces next to the
    current story they relate to (e.g. a 25.01.2026 article on 24.10.2026). The node only
    deduped by URL, so each one was ingested as a "new" article, classified, scraped and
    summarized, and showed up as "9 ay önce"."""
    now = datetime.now(timezone.utc)
    urls = _run_fetcher_with(monkeypatch, db_session, [
        _dated_entry("https://example.com/fresh", now - timedelta(hours=2)),
        _dated_entry("https://example.com/background", now - timedelta(days=272)),
        _dated_entry("https://example.com/undated", None),
    ])
    # Default limit is 72h; an entry without a date can't be judged and is kept.
    assert urls == ["https://example.com/fresh", "https://example.com/undated"]


def test_rss_fetcher_node_max_age_follows_setting(monkeypatch, db_session):
    now = datetime.now(timezone.utc)
    entries = [_dated_entry("https://example.com/five-days", now - timedelta(days=5))]

    crud.set_setting(db_session, "max_article_age_hours", "168")
    assert _run_fetcher_with(monkeypatch, db_session, entries) == ["https://example.com/five-days"]

    crud.set_setting(db_session, "max_article_age_hours", "24")
    assert _run_fetcher_with(monkeypatch, db_session, entries) == []

    crud.set_setting(db_session, "max_article_age_hours", "0")  # 0 = no limit
    assert _run_fetcher_with(monkeypatch, db_session, entries) == ["https://example.com/five-days"]


# ---------------------------------------------------------------------------
# Full feed pipeline (rss_fetcher -> article processing) with OpenAI/scraping stubbed
# (the `pipeline_env` fixture lives in conftest.py)
# ---------------------------------------------------------------------------


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


_FEED_HTML = "".join(f"<p>Tam haber metni paragraf {i}, " + "ayrıntı " * 10 + "</p>" for i in range(20))


def _run_with_page(pipeline_env, db_session, monkeypatch, page, raw_content):
    """Run one important article through the pipeline with the page fetch answering `page`;
    returns (article, scraped urls, contents handed to the summarizer)."""
    from app.services import summary_service
    from app.tasks import background

    scraped, summarized = [], []

    async def tracking_extract(url):
        scraped.append(url)
        return page

    async def tracking_summary(title, content, summary_type="standard", source=None, author_hint=None):
        summarized.append(content)
        return {"summary_text": "s", "model_used": "m", "tokens_used": 1, "cost": 0.0,
                "author": None, "structured": True}

    monkeypatch.setattr(summary_service, "extract_article_content", tracking_extract)
    monkeypatch.setattr(summary_service, "generate_summary", tracking_summary)
    feed = _make_feed(db_session)
    pipeline_env.rss_entries = [dict(_rss_entry(1), raw_content=raw_content)]

    asyncio.run(background.process_feed_async(feed.id))

    db_session.expire_all()
    return crud.get_article_by_url(db_session, "https://example.com/news-1"), scraped, summarized


def test_pipeline_falls_back_to_feed_full_text_when_the_page_is_blocked(pipeline_env, db_session, monkeypatch):
    """Politico's pages 403 the scraper, but its feed carries the whole article in
    <content:encoded> (kept as raw_content). That text becomes the article text and is summarized,
    instead of the HTML being sent to the model or only a teaser being summarized."""
    article, scraped, summarized = _run_with_page(
        pipeline_env, db_session, monkeypatch, (None, None, None), _FEED_HTML)

    assert scraped == ["https://example.com/news-1"]  # the page is still tried first
    assert article.status == "summarized"
    assert article.cleaned_content.startswith("Tam haber metni paragraf 0")
    assert len(article.cleaned_content.split("\n")) == 20 and "<p>" not in article.cleaned_content
    assert summarized and all(c.startswith("Tam haber metni paragraf 0") for c in summarized)


def test_pipeline_prefers_feed_full_text_over_a_shorter_paywalled_page(pipeline_env, db_session, monkeypatch):
    article, _, summarized = _run_with_page(
        pipeline_env, db_session, monkeypatch, ("Abone olun. Kısa giriş.", None, "https://img/x.jpg"), _FEED_HTML)

    assert article.cleaned_content.startswith("Tam haber metni paragraf 0")
    assert article.image_url == "https://img/x.jpg"  # page metadata is still used
    assert all(c.startswith("Tam haber metni") for c in summarized)


def test_pipeline_keeps_the_page_and_its_metadata_when_it_has_the_article(pipeline_env, db_session, monkeypatch):
    """Using the feed text up front skipped the page, and with it og:image and the page author.
    The page wins whenever it has at least as much text as the feed."""
    page_text = "Sayfadaki tam metin. " * 400
    article, _, _ = _run_with_page(
        pipeline_env, db_session, monkeypatch, (page_text, "Yazar Adı", "https://img/hero.jpg"), _FEED_HTML)

    assert article.cleaned_content == page_text
    assert article.image_url == "https://img/hero.jpg"


def test_short_feed_text_is_not_taken_for_the_article(pipeline_env, db_session, monkeypatch):
    # A teaser in the feed (NYT/Spiegel) must not be stored as the article text: a later fetch
    # ("Orijinal İçerik", bulletin) should try the page again.
    article, _, _ = _run_with_page(
        pipeline_env, db_session, monkeypatch, (None, None, None), "<p>Kısa bir RSS girişi.</p>")

    assert article.cleaned_content is None


def test_fetch_article_content_falls_back_to_feed_full_text(db_session, monkeypatch):
    """The "Orijinal İçerik" view and the bulletin get their text from fetch_article_content —
    the same page-or-feed rule as the pipeline applies there."""
    from app.services import summary_service

    async def blocked(url):
        return None, None, None

    monkeypatch.setattr(summary_service, "extract_article_content", blocked)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="filtered", raw_content=_FEED_HTML, cleaned_content=None)

    text = asyncio.run(summary_service.fetch_article_content(db_session, article.id))

    assert text.startswith("Tam haber metni paragraf 0")
    db_session.expire_all()
    assert crud.get_article(db_session, article.id).cleaned_content == text


_LONG_PAGE = "\n".join(f"Tam metin paragraf {i} yeterince uzun bir cümle içerir." for i in range(40))


@pytest.mark.parametrize("page, searched", [
    ((None, None, None, False, True), True),         # blocked: 401/403/robots.txt — no page text
    (("Kurzer Vorspann.", None, None, True, False), True),  # paywalled page: only the lead
    ((_LONG_PAGE, None, None, False, False), False),  # the article was read
    ((_LONG_PAGE, None, None, True, False), False),   # paywall flag but the whole text came through
    # Regression (review): no text for a reason other than the source refusing us — scraping
    # disabled, 404/5xx, an empty extraction — is not "paywalled or blocked".
    ((None, None, None, False, False), False),
    ((None, None, None), False),
])
def test_pipeline_searches_free_sources_only_when_the_page_gave_no_article(
        pipeline_env, db_session, monkeypatch, free_match_calls, page, searched):
    article, _, _ = _run_with_page(pipeline_env, db_session, monkeypatch, page, "<p>RSS girişi.</p>")

    assert article.status == "summarized"
    assert (free_match_calls == [article.id]) is searched


def test_a_failed_page_fetch_does_not_label_the_article(pipeline_env, db_session, monkeypatch, free_match_calls):
    """Regression (review): a timeout / ScrapingError left no_article_text True, so a transient
    error got the permanent "İçerik alınamadı" label and a paid search."""
    from app.services import summary_service

    async def timeout(url):
        raise summary_service.ScrapingError("HTTP error: timeout")

    monkeypatch.setattr(summary_service, "extract_article_content", timeout)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", raw_content="<p>RSS girişi.</p>")

    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    assert crud.get_article(db_session, article.id).status == "summarized"
    assert free_match_calls == []


def test_reprocess_keeps_the_label_when_the_page_is_not_fetched_again(pipeline_env, db_session):
    """Regression (review): an article whose stored cleaned_content is only the paywall lead isn't
    fetched again on re-process — and its "unavailable" label was wiped anyway."""
    from app.services import summary_service

    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content="Kurzer Vorspann.")
    crud.set_article_content_access(db_session, article.id, "unavailable")

    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    assert pipeline_env.extracted_urls == []
    assert crud.get_article(db_session, article.id).content_access == "unavailable"


def test_a_paywalled_article_whose_summaries_fail_is_labelled_and_searched_on_reprocess(
        pipeline_env, db_session, monkeypatch, free_match_calls):
    """Regression (review): the label was only written after a successful summary. When all
    summaries failed, the stored paywall lead made the re-process skip the page fetch, so the
    article was summarized from the lead without any label or free-source search."""
    from app.db import database
    from app.services import summary_service

    async def lead_only(url):
        return "Kurzer Vorspann.", None, None, True, False

    monkeypatch.setitem(database.vector_support, "available", True)

    async def down(**kwargs):
        raise RuntimeError("OpenAI down")

    monkeypatch.setattr(summary_service, "extract_article_content", lead_only)
    monkeypatch.setattr(summary_service, "generate_summary", down)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", raw_content="<p>RSS girişi.</p>")

    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    failed = crud.get_article(db_session, article.id)
    assert failed.status == "failed"
    assert failed.content_access == "unavailable"
    assert free_match_calls == []

    async def works(title, content, summary_type="standard", source=None, author_hint=None):
        return {"summary_text": "s", "model_used": "m", "tokens_used": 1, "cost": 0.0,
                "author": None, "structured": True}

    monkeypatch.setattr(summary_service, "generate_summary", works)
    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    assert crud.get_article(db_session, article.id).status == "summarized"
    assert free_match_calls == [article.id]


def test_without_pgvector_a_paywalled_article_gets_no_early_label(pipeline_env, db_session, monkeypatch):
    """No search can run without pgvector, so the early "unavailable" label isn't written either."""
    from app.db import database
    from app.services import summary_service

    async def lead_only(url):
        return "Kurzer Vorspann.", None, None, True, False

    monkeypatch.setitem(database.vector_support, "available", False)
    monkeypatch.setattr(summary_service, "extract_article_content", lead_only)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="pending", raw_content="<p>RSS girişi.</p>")

    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    assert crud.get_article(db_session, article.id).content_access is None


def test_reprocess_with_full_text_clears_an_old_access_label(pipeline_env, db_session, monkeypatch):
    from app.services import summary_service

    async def full_page(url):
        return _LONG_PAGE, None, None, False

    monkeypatch.setattr(summary_service, "extract_article_content", full_page)
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status="failed", cleaned_content=None)
    crud.set_article_content_access(db_session, article.id, "unavailable")

    asyncio.run(summary_service.process_article(db_session, article.id))

    db_session.expire_all()
    assert crud.get_article(db_session, article.id).content_access is None
