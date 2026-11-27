"""
Tests for POST /api/articles/manual — admin-added articles (form / JSON upload) that run through
the same pipeline as feed articles. (403/401 for non-admins: tests/test_permissions.py.)
"""
import pytest

from app.db import models
from app.tasks import background
from tests.conftest import _make_article, _make_feed

URL = "/api/articles/manual"


@pytest.fixture()
def queued(monkeypatch):
    """Capture the ids handed to the background pipeline instead of running it."""
    calls = []

    async def fake_task(article_ids):
        calls.append(list(article_ids))

    monkeypatch.setattr(background, "reprocess_articles_task", fake_task)
    return calls


def _articles(db_session):
    return db_session.query(models.Article).order_by(models.Article.id).all()


def test_admin_adds_article_with_content(client, admin_headers, db_session, queued):
    feed = _make_feed(db_session, title="DW - Deutsche Welle")
    body = {"articles": [{
        "title": "  Almanya'da yeni göç yasası  ",
        "feed_id": feed.id,
        "content": "Federal Meclis bugün yasayı kabul etti.",
        "url": "https://example.com/haber/123",
        "author": "Ayşe Yılmaz",
        "published_at": "2026-11-27T09:30:00Z",
        "image_url": "https://example.com/img.jpg",
    }]}

    response = client.post(URL, json=body, headers=admin_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["queued"] == 1 and data["skipped"] == [] and data["errors"] == []
    [article] = _articles(db_session)
    assert data["created"] == [{"index": 0, "article_id": article.id, "title": "Almanya'da yeni göç yasası"}]
    assert article.source_type == "manual"
    assert article.status == "pending"
    assert article.feed_id == feed.id
    assert article.url == "https://example.com/haber/123"
    assert article.cleaned_content == "Federal Meclis bugün yasayı kabul etti."
    assert article.author == "Ayşe Yılmaz"
    assert article.image_url == "https://example.com/img.jpg"
    assert article.published_at.year == 2026
    assert queued == [[article.id]]
    # The list API exposes the origin so the card can show "Manuel".
    listed = client.get("/api/articles/", headers=admin_headers).json()["articles"]
    assert listed[0]["source_type"] == "manual"


def test_article_without_url_gets_a_unique_manual_url(client, admin_headers, db_session, queued):
    feed = _make_feed(db_session)
    item = {"title": "Kendi haberim", "feed_id": feed.id, "content": "Metin"}

    response = client.post(URL, json={"articles": [item, dict(item)]}, headers=admin_headers)

    assert response.status_code == 200
    urls = [a.url for a in _articles(db_session)]
    assert len(urls) == 2 and len(set(urls)) == 2
    assert all(u.startswith("manual://") for u in urls)
    assert all(a.published_at is not None for a in _articles(db_session))


def test_feed_by_title_unknown_feed_and_duplicate_url(client, admin_headers, db_session, queued):
    feed = _make_feed(db_session, title="DW - Deutsche Welle")
    _make_article(db_session, feed.id, url="https://example.com/var-olan")
    body = {"articles": [
        {"title": "Başlıkla kaynak", "feed": "  dw - deutsche welle ", "content": "Metin"},
        {"title": "Olmayan kaynak", "feed": "Yok Böyle Kaynak", "content": "Metin"},
        {"title": "Tekrar", "feed_id": feed.id, "url": "https://example.com/var-olan"},
        {"title": "Olmayan id", "feed_id": 9999, "content": "Metin"},
    ]}

    data = client.post(URL, json=body, headers=admin_headers).json()

    assert [c["index"] for c in data["created"]] == [0]
    assert [s["index"] for s in data["skipped"]] == [2]
    assert [e["index"] for e in data["errors"]] == [1, 3]
    assert data["errors"][0]["reason"] == "Kaynak bulunamadı"
    assert data["queued"] == 1
    created = db_session.get(models.Article, data["created"][0]["article_id"])
    assert created.feed_id == feed.id


def test_duplicate_url_within_one_upload_is_skipped(client, admin_headers, db_session, queued):
    feed = _make_feed(db_session)
    item = {"title": "Aynı link", "feed_id": feed.id, "url": "https://example.com/a"}

    data = client.post(URL, json={"articles": [item, dict(item)]}, headers=admin_headers).json()

    assert len(data["created"]) == 1 and [s["index"] for s in data["skipped"]] == [1]


def test_url_is_stored_as_given_so_an_rss_duplicate_is_found(client, admin_headers, db_session, queued):
    """Regression (review): HttpUrl percent-encoded non-ASCII paths / added a trailing "/", so the
    duplicate check missed the same URL stored by RSS and the story was summarized twice."""
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, url="https://site.com/haber/göç-yasası")
    body = {"articles": [
        {"title": "Aynı haber", "feed_id": feed.id, "url": "https://site.com/haber/göç-yasası"},
        {"title": "Kök adres", "feed_id": feed.id, "url": " https://site.com "},
    ]}

    data = client.post(URL, json=body, headers=admin_headers).json()

    assert [s["index"] for s in data["skipped"]] == [0]
    created = db_session.get(models.Article, data["created"][0]["article_id"])
    assert created.url == "https://site.com"


@pytest.mark.parametrize("stored, given", [
    ("İstanbul Haber", "istanbul haber"),
    ("İstanbul Haber", "ISTANBUL HABER"),
    ("Bild", "BILD"),
    ("  Spiegel  ", "spiegel"),
])
def test_feed_title_match_handles_turkish_i_and_spaces(client, admin_headers, db_session, queued, stored, given):
    """Regression (review): Python lower() vs SQL lower() disagreed on İ/I (and the stored title
    wasn't trimmed), so a feed the preview resolved came back as "Kaynak bulunamadı"."""
    feed = _make_feed(db_session, title=stored)
    body = {"articles": [{"title": "Haber", "feed": given, "content": "Metin"}]}

    data = client.post(URL, json=body, headers=admin_headers).json()

    assert data["errors"] == []
    assert db_session.get(models.Article, data["created"][0]["article_id"]).feed_id == feed.id


def test_a_failing_entry_does_not_strand_the_ones_already_created(
    client, admin_headers, db_session, queued, monkeypatch
):
    """Regression (review): each create commits; an exception on a later entry (e.g. a URL
    inserted concurrently) returned 500 before queueing, leaving earlier ones "pending" forever."""
    from sqlalchemy.exc import IntegrityError
    from app.db import crud

    feed = _make_feed(db_session)
    real_create = crud.create_article

    def flaky_create(db, **kwargs):
        if kwargs["title"] == "Çakışan":
            raise IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))
        return real_create(db, **kwargs)

    monkeypatch.setattr(crud, "create_article", flaky_create)
    body = {"articles": [
        {"title": "Birinci", "feed_id": feed.id, "content": "Metin"},
        {"title": "Çakışan", "feed_id": feed.id, "url": "https://example.com/x"},
        {"title": "Üçüncü", "feed_id": feed.id, "content": "Metin"},
    ]}

    response = client.post(URL, json=body, headers=admin_headers)

    assert response.status_code == 200
    data = response.json()
    assert [c["index"] for c in data["created"]] == [0, 2]
    assert [s["index"] for s in data["skipped"]] == [1]
    assert queued == [[c["article_id"] for c in data["created"]]]


def test_url_less_manual_article_is_not_a_free_source_candidate(db_session, monkeypatch):
    """Regression (review): a manual article without a link could be offered as the free source
    of a blocked story, and the card linked to its dead manual:// address."""
    from app.db import crud

    blocked_feed = _make_feed(db_session, url="https://example.com/wsj")
    other_feed = _make_feed(db_session, url="https://example.com/other")
    blocked = _make_article(db_session, blocked_feed.id, url="https://wsj.example/a")
    manual = _make_article(db_session, other_feed.id, url="manual://1234", status="summarized")
    free = _make_article(db_session, other_feed.id, url="https://dw.example/a", status="summarized")
    captured = {}

    def fake_nearest(db, model, columns, vector, scope, limit):
        captured["ids"] = {row.id for row in db.execute(scope)}
        return []

    monkeypatch.setattr(crud, "_nearest", fake_nearest)
    crud.free_match_candidates(db_session, blocked.id, [0.0], window_hours=48, limit=5)

    assert free.id in captured["ids"]
    assert manual.id not in captured["ids"]


@pytest.mark.parametrize("item", [
    {"title": "İçeriksiz", "feed_id": 1},                                       # no content, no url
    {"title": "İçeriksiz", "feed_id": 1, "content": "   "},                     # blank content
    {"title": "Kaynaksız", "content": "Metin"},                                 # no feed
    {"title": "ab", "feed_id": 1, "content": "Metin"},                          # title too short
    {"title": "Dosya", "feed_id": 1, "url": "file:///etc/passwd"},              # non-http url
    {"title": "Tarih", "feed_id": 1, "content": "Metin", "published_at": "dün"},  # bad date
])
def test_invalid_entries_are_rejected(client, admin_headers, db_session, queued, item):
    _make_feed(db_session)
    response = client.post(URL, json={"articles": [item]}, headers=admin_headers)
    assert response.status_code == 422
    assert _articles(db_session) == [] and queued == []


@pytest.mark.parametrize("count", [0, 51])
def test_batch_size_is_bounded(client, admin_headers, db_session, queued, count):
    feed = _make_feed(db_session)
    items = [{"title": f"Haber {i}", "feed_id": feed.id, "content": "Metin"} for i in range(count)]
    assert client.post(URL, json={"articles": items}, headers=admin_headers).status_code == 422


def test_manual_article_runs_through_the_pipeline_without_scraping(
    client, admin_headers, db_session, pipeline_env
):
    """The queued article goes through summary_service.process_article like a feed article:
    classified, summarized, status "summarized" — and its own text is used, no page fetch."""
    feed = _make_feed(db_session)
    body = {"articles": [{"title": "Kendi haberim", "feed_id": feed.id, "content": "Kullanıcı metni"}]}

    response = client.post(URL, json=body, headers=admin_headers)  # TestClient runs background tasks

    assert response.status_code == 200
    db_session.expire_all()
    [article] = _articles(db_session)
    assert article.status == "summarized"
    assert article.priority == "high"
    assert article.summaries
    assert pipeline_env.extracted_urls == []
    assert article.url.startswith("manual://")


def test_inactive_feeds_are_not_offered_nor_accepted(client, admin_headers, db_session, queued):
    """Regression (review): the dialog lists only active feeds, but the backend resolved inactive
    ones too — a row the preview dropped was accepted, and with an inactive and an active feed of
    the same title the article landed in the hidden (lower-id) one."""
    old = _make_feed(db_session, "https://old.example/feed", title="BBC Türkçe")
    old.is_active = False
    db_session.commit()
    active = _make_feed(db_session, "https://bbc.example/feed", title="BBC Türkçe")
    body = {"articles": [
        {"title": "Başlıkla", "feed": "BBC Türkçe", "content": "Metin"},
        {"title": "Pasif id", "feed_id": old.id, "content": "Metin"},
    ]}

    data = client.post(URL, json=body, headers=admin_headers).json()

    assert [c["index"] for c in data["created"]] == [0]
    assert db_session.get(models.Article, data["created"][0]["article_id"]).feed_id == active.id
    assert [(e["index"], e["reason"]) for e in data["errors"]] == [(1, "Kaynak bulunamadı")]
