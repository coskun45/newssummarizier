"""
Tests for app/api/routes/bulletin.py.
"""
import io
import zipfile
from datetime import datetime, timedelta, timezone

from docx import Document as DocxDocument

from app.core.config import settings as app_settings
from app.db import models
from app.services import bulletin_service
from tests.conftest import _make_article, _make_feed


def _make_bulletin_category(db_session, name="AVRUPA", display_order=0):
    category = models.BulletinCategory(name=name, display_order=display_order)
    db_session.add(category)
    db_session.commit()
    db_session.refresh(category)
    return category


# ==================== GET /categories (list) ====================

def test_list_categories_requires_auth(client):
    response = client.get("/api/bulletin/categories")
    assert response.status_code == 401


def test_list_categories_empty(client, auth_headers):
    response = client.get("/api/bulletin/categories", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_categories_returns_display_order(client, auth_headers, db_session):
    _make_bulletin_category(db_session, name="AMERİKA", display_order=1)
    _make_bulletin_category(db_session, name="AVRUPA", display_order=0)

    response = client.get("/api/bulletin/categories", headers=auth_headers)

    assert response.status_code == 200
    assert [c["name"] for c in response.json()] == ["AVRUPA", "AMERİKA"]


# ==================== POST /categories (create) ====================

def test_create_category_requires_admin(client, auth_headers):
    response = client.post("/api/bulletin/categories", json={"name": "AVRUPA"}, headers=auth_headers)
    assert response.status_code == 403


def test_create_category_success(client, admin_headers):
    response = client.post("/api/bulletin/categories", json={"name": "AVRUPA"}, headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "AVRUPA"


def test_create_category_rejects_duplicate_name(client, admin_headers, db_session):
    _make_bulletin_category(db_session, name="AVRUPA")

    response = client.post("/api/bulletin/categories", json={"name": "AVRUPA"}, headers=admin_headers)

    assert response.status_code == 400


def test_create_category_rejects_empty_name(client, admin_headers):
    response = client.post("/api/bulletin/categories", json={"name": "   "}, headers=admin_headers)
    assert response.status_code == 400


# ==================== PUT /categories/{id} (update) ====================

def test_update_category_requires_admin(client, auth_headers, db_session):
    category = _make_bulletin_category(db_session)
    response = client.put(
        f"/api/bulletin/categories/{category.id}", json={"name": "AMERİKA"}, headers=auth_headers
    )
    assert response.status_code == 403


def test_update_category_renames(client, admin_headers, db_session):
    category = _make_bulletin_category(db_session, name="AVRUPA")

    response = client.put(
        f"/api/bulletin/categories/{category.id}", json={"name": "AMERİKA"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "AMERİKA"


def test_update_category_404_when_missing(client, admin_headers):
    response = client.put("/api/bulletin/categories/999999", json={"name": "X"}, headers=admin_headers)
    assert response.status_code == 404


# ==================== DELETE /categories/{id} ====================

def test_delete_category_requires_admin(client, auth_headers, db_session):
    category = _make_bulletin_category(db_session)
    response = client.delete(f"/api/bulletin/categories/{category.id}", headers=auth_headers)
    assert response.status_code == 403


def test_delete_category_success(client, admin_headers, db_session):
    category = _make_bulletin_category(db_session)
    response = client.delete(f"/api/bulletin/categories/{category.id}", headers=admin_headers)
    assert response.status_code == 200


def test_delete_category_404_when_missing(client, admin_headers):
    response = client.delete("/api/bulletin/categories/999999", headers=admin_headers)
    assert response.status_code == 404


# ==================== PUT /categories/reorder ====================

def test_reorder_categories_requires_admin(client, auth_headers, db_session):
    category = _make_bulletin_category(db_session)
    response = client.put(
        "/api/bulletin/categories/reorder", json={"ordered_ids": [category.id]}, headers=auth_headers
    )
    assert response.status_code == 403


def test_reorder_categories_success(client, admin_headers, db_session):
    a = _make_bulletin_category(db_session, name="AVRUPA", display_order=0)
    b = _make_bulletin_category(db_session, name="AMERİKA", display_order=1)

    response = client.put(
        "/api/bulletin/categories/reorder",
        json={"ordered_ids": [b.id, a.id]},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert [c["name"] for c in response.json()] == ["AMERİKA", "AVRUPA"]


# ==================== POST /generate ====================

def test_generate_bulletin_requires_auth(client):
    response = client.post("/api/bulletin/generate", json={})
    assert response.status_code == 401


def test_generate_bulletin_no_categories_returns_400(client, auth_headers):
    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)
    assert response.status_code == 400


def test_generate_bulletin_no_articles_returns_400(client, auth_headers, db_session):
    _make_bulletin_category(db_session, name="AVRUPA")

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 400


def test_generate_bulletin_rejects_invalid_priority(client, auth_headers, db_session):
    _make_bulletin_category(db_session, name="AVRUPA")

    response = client.post(
        "/api/bulletin/generate", json={"priorities": ["urgent"]}, headers=auth_headers
    )

    assert response.status_code == 400


async def _fake_classify(db, articles, category_names):
    if not articles:
        return []
    return [
        {"article_id": a.id, "top_category": category_names[0], "subcategory": "Test Alt Başlık", "type": "haber"}
        for a in articles
    ]


async def _fake_digest(articles, limit=8):
    return [{"article_id": a.id, "blurb": f"{a.title} özeti."} for a in articles[:limit]]


def test_generate_bulletin_success(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(
        db_session, feed.id, title="Test Haberi", priority="high",
        published_at=now - timedelta(hours=1),
    )

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.content[:4] == b"PK\x03\x04"

    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]
    assert any("AVRUPA" in t for t in paragraph_texts)
    assert any("özeti" in t for t in paragraph_texts)

    # "BAZI KAYNAKLAR" reflects the actually-configured feed, not the
    # template's static example source list.
    assert any(feed.url in t for t in paragraph_texts)
    assert not any("Associated Press" in t for t in paragraph_texts)

    # Top category -> Heading1, subcategory -> Heading2, matching the
    # template's own TOC field mapping ("Heading 1,1,Heading 2,2,...") —
    # using Heading3 here (an earlier version of this code did) leaves the
    # TOC's level-2 slot empty once Word recomputes it.
    by_text = {p.text.strip(): p.style.style_id for p in document.paragraphs if p.text.strip()}
    assert by_text["AVRUPA"] == "Heading1"
    assert by_text["Test Alt Başlık"] == "Heading2"

    # The TOC can't be recomputed by python-docx, so Word is told to refresh
    # every field (the TOC included) on open instead of showing the
    # template's stale cached result.
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        settings_xml = zf.read("word/settings.xml").decode("utf-8")
    assert '<w:updateFields w:val="true"/>' in settings_xml


def test_generate_bulletin_uses_only_user_defined_categories(client, auth_headers, db_session, monkeypatch):
    """A category set unrelated to the bundled template's default region
    headings must fully replace them in the output — regression test for a
    reported issue where the generated report appeared to ignore
    user-created categories."""
    async def classify_into_custom_categories(db, articles, category_names):
        return [
            {"article_id": a.id, "top_category": category_names[0], "subcategory": "Alt Başlık", "type": "haber"}
            for a in articles
        ]

    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", classify_into_custom_categories)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="Teknoloji")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Yapay Zeka Haberi", published_at=now - timedelta(hours=1))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]

    assert any("Teknoloji" in t for t in paragraph_texts)
    template_default_headings = [
        "AMERIKA", "AVRUPA", "RUSYA / UKRAYNA", "TÜRKİYE",
        "KAFKASYA / ORTADOĞU", "AFRIKA", "ASYA", "TEKNOLOJI / YAPAY ZEKA",
    ]
    leaked = [h for h in template_default_headings if any(h in t for t in paragraph_texts)]
    assert leaked == []


def test_generate_bulletin_too_many_articles_returns_400(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)
    monkeypatch.setattr(app_settings, "bulletin_max_articles", 2)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    for i in range(3):
        _make_article(db_session, feed.id, title=f"Article {i}", published_at=now - timedelta(hours=1))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 400


def test_generate_bulletin_uses_classification_cache(client, auth_headers, db_session, monkeypatch):
    call_count = {"n": 0}

    async def counting_classify(db, articles, category_names):
        if not articles:
            return []
        call_count["n"] += 1
        return [
            {"article_id": a.id, "top_category": category_names[0], "subcategory": "Test", "type": "haber"}
            for a in articles
        ]

    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", counting_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Cached Haber", published_at=now - timedelta(hours=1))

    first = client.post("/api/bulletin/generate", json={}, headers=auth_headers)
    assert first.status_code == 200
    assert call_count["n"] == 1

    second = client.post("/api/bulletin/generate", json={}, headers=auth_headers)
    assert second.status_code == 200
    assert call_count["n"] == 1  # second run served entirely from the classification cache
