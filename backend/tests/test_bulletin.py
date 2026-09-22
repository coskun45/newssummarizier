"""
Tests for app/api/routes/bulletin.py.
"""
import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from docx import Document as DocxDocument

from app.core.config import settings as app_settings
from app.db import crud, models
from app.services import bulletin_service
from tests.conftest import _make_article, _make_feed


@pytest.fixture(autouse=True)
def _isolated_bulletin_storage(tmp_path, monkeypatch):
    """Every /generate call now writes a .docx to BULLETIN_STORAGE_DIR — redirect
    it to a pytest tmp dir so tests never write into the real repo checkout."""
    monkeypatch.setattr(app_settings, "bulletin_storage_dir", str(tmp_path))


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


def test_create_category_rejects_case_insensitive_duplicate(client, admin_headers, db_session):
    """"Avrupa" and "AVRUPA" fold to the same key in
    docx_service._normalize() and would collide onto the same template
    heading when rendering a bulletin — the exact-match check let both be
    created. Regression test for get_bulletin_category_by_name's
    case/Turkish-I-insensitive lookup."""
    _make_bulletin_category(db_session, name="Avrupa")

    response = client.post("/api/bulletin/categories", json={"name": "AVRUPA"}, headers=admin_headers)

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


def test_update_category_rejects_case_insensitive_duplicate(client, admin_headers, db_session):
    _make_bulletin_category(db_session, name="Avrupa", display_order=0)
    other = _make_bulletin_category(db_session, name="AMERİKA", display_order=1)

    response = client.put(
        f"/api/bulletin/categories/{other.id}", json={"name": "avrupa"}, headers=admin_headers
    )

    assert response.status_code == 400


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


def test_generate_bulletin_strips_html_from_raw_content_fallback(client, auth_headers, db_session, monkeypatch):
    """Regression test: when an article has no "brief" summary yet,
    bulletin_service._article_snippet falls back to raw_content, which for
    several feeds (e.g. Aydinlik) is an HTML fragment straight from the RSS
    <description> rather than plain text. A real generated bulletin showed
    this markup — <a>/<img>/<h4> tags and &#039;-style entities — rendered
    verbatim as visible text in the Word document."""
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(
        db_session, feed.id, title="HTML Kirli Haber",
        raw_content=(
            '<a href="https://example.com/haber">'
            '<img align="right" border="0" height="84" src="https://img.example.com/x.jpg" width="150" />'
            '</a>\n<h4>Firari şüpheli &#039;yakalandı&#039;</h4>'
        ),
        published_at=now - timedelta(hours=1),
    )

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]

    assert not any("<a href" in t or "<img " in t or "<h4>" in t for t in paragraph_texts)
    assert any("Firari şüpheli 'yakalandı'" in t for t in paragraph_texts)


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


def test_generate_bulletin_respects_display_order(client, auth_headers, db_session, monkeypatch):
    """The bundled template's Heading1 paragraphs sit in a fixed physical
    order (AMERIKA before AVRUPA). Regression test for a reported issue where
    the generated report's index/table-of-contents always followed that
    fixed template order instead of the user-configured display_order."""
    async def classify_by_display_order(db, articles, category_names):
        return [
            {"article_id": a.id, "top_category": category_names[i], "subcategory": "Alt Başlık", "type": "haber"}
            for i, a in enumerate(articles)
        ]

    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", classify_by_display_order)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    # AMERIKA precedes AVRUPA in the template's physical layout, but the
    # user has configured the opposite display_order here.
    _make_bulletin_category(db_session, name="AMERIKA", display_order=1)
    _make_bulletin_category(db_session, name="AVRUPA", display_order=0)
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Avrupa Haberi", published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, title="Amerika Haberi", published_at=now - timedelta(hours=2))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    heading1_texts = [p.text.strip() for p in document.paragraphs if p.style.style_id == "Heading1" and p.text.strip()]

    assert heading1_texts.index("AVRUPA") < heading1_texts.index("AMERIKA")


def test_generate_bulletin_case_variant_categories_get_separate_headings(
    client, auth_headers, db_session, monkeypatch
):
    """"Avrupa" and "AVRUPA" both fold to the same key under
    docx_service._normalize() (Turkish-I-aware case-fold). Categories this
    close can't be created via the admin API anymore (case-insensitive
    duplicate check), but this models a database that predates that guard by
    writing the row directly. Regression test for
    docx_service._rebuild_category_sections handing the SAME template
    heading paragraph to both categories (`existing_by_name.get()` never
    removed the entry) — the second category would relocate the first one's
    already-placed heading out from under its own content, stranding the
    first category's articles above an orphaned heading."""
    async def classify_by_category_names(db, articles, category_names):
        return [
            {"article_id": a.id, "top_category": category_names[i], "subcategory": "Alt Başlık", "type": "haber"}
            for i, a in enumerate(articles)
        ]

    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", classify_by_category_names)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="Avrupa", display_order=0)
    _make_bulletin_category(db_session, name="AVRUPA", display_order=1)
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Avrupa Haberi", published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, title="Ikinci Avrupa Haberi", published_at=now - timedelta(hours=2))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))

    heading1_avrupa_indices = [
        i for i, p in enumerate(document.paragraphs)
        if p.style.style_id == "Heading1" and p.text.strip().upper() == "AVRUPA"
    ]
    assert len(heading1_avrupa_indices) == 2, (
        "each case-variant category must get its own Heading1 paragraph, not "
        "share/relocate the other's"
    )

    paragraph_texts = [p.text for p in document.paragraphs]
    first_heading_idx, second_heading_idx = heading1_avrupa_indices
    # The article body paragraph (with its "(source)" suffix) is distinct
    # from the GÜNDEM ÖZETİ digest blurb (which ends in "özeti." instead and
    # always precedes the category sections) — search on the former so this
    # doesn't accidentally match the digest mention of the same title.
    first_article_idx = next(i for i, t in enumerate(paragraph_texts) if "Avrupa Haberi (example.com)" in t)
    second_article_idx = next(
        i for i, t in enumerate(paragraph_texts) if "Ikinci Avrupa Haberi (example.com)" in t
    )

    # Each category's article must sit under its OWN heading, not stranded
    # above it or under the other category's heading.
    assert first_heading_idx < first_article_idx < second_heading_idx < second_article_idx


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


# ==================== POST /generate — favorites ====================

def test_generate_bulletin_include_favorites_only(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(
        db_session, feed.id, title="Favori Haber", is_starred=True,
        published_at=now - timedelta(hours=1),
    )
    _make_article(
        db_session, feed.id, title="Normal Haber", is_starred=False,
        published_at=now - timedelta(hours=1),
    )

    response = client.post(
        "/api/bulletin/generate", json={"include_favorites": True}, headers=auth_headers
    )

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]
    assert any("Favori Haber" in t for t in paragraph_texts)
    assert not any("Normal Haber" in t for t in paragraph_texts)


def test_generate_bulletin_priorities_and_favorites_union(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(
        db_session, feed.id, title="Yuksek Oncelik", priority="high", is_starred=False,
        published_at=now - timedelta(hours=1),
    )
    _make_article(
        db_session, feed.id, title="Favori Dusuk Oncelik", priority="low", is_starred=True,
        published_at=now - timedelta(hours=1),
    )
    _make_article(
        db_session, feed.id, title="Orta Oncelik Disarida", priority="med", is_starred=False,
        published_at=now - timedelta(hours=1),
    )

    response = client.post(
        "/api/bulletin/generate",
        json={"priorities": ["high"], "include_favorites": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]
    assert any("Yuksek Oncelik" in t for t in paragraph_texts)
    assert any("Favori Dusuk Oncelik" in t for t in paragraph_texts)
    assert not any("Orta Oncelik Disarida" in t for t in paragraph_texts)


def test_generate_bulletin_dedup_when_article_matches_both(client, auth_headers, db_session, monkeypatch):
    """An article that is both a matching priority AND starred must appear
    exactly once in the bulletin, not twice."""
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(
        db_session, feed.id, title="Hem Yuksek Hem Favori", priority="high", is_starred=True,
        published_at=now - timedelta(hours=1),
    )

    response = client.post(
        "/api/bulletin/generate",
        json={"priorities": ["high"], "include_favorites": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    paragraph_texts = [p.text for p in document.paragraphs if p.text.strip()]
    # The digest ("GÜNDEM ÖZETİ") and the category listing are two distinct
    # sections that both legitimately reference every selected article once —
    # so the real assertion is "not selected twice into the category listing",
    # which is where a broken union (fetching the article via two separate
    # queries instead of one OR'd query) would show up as a duplicate entry.
    category_entries = [t for t in paragraph_texts if "Hem Yuksek Hem Favori" in t and "(example.com)" in t]
    assert len(category_entries) == 1


def test_generate_bulletin_include_favorites_defaults_false(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    # Starred but priority doesn't match anything requested, and the request
    # doesn't mention include_favorites at all (mirrors test_generate_bulletin_success).
    _make_article(
        db_session, feed.id, title="Favori Ama Istenmedi", priority="low", is_starred=True,
        published_at=now - timedelta(hours=1),
    )

    response = client.post(
        "/api/bulletin/generate", json={"priorities": ["high"]}, headers=auth_headers
    )

    assert response.status_code == 400  # nothing matches priority "high" and favorites weren't requested


# ==================== GET /preview-count ====================

def test_preview_count_requires_auth(client):
    response = client.get("/api/bulletin/preview-count")
    assert response.status_code == 401


def test_preview_count_defaults_to_last_24h_all_priorities(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Icerde 1", published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, title="Icerde 2", published_at=now - timedelta(hours=2))
    _make_article(db_session, feed.id, title="Disarda", published_at=now - timedelta(hours=48))

    response = client.get("/api/bulletin/preview-count", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_preview_count_filters_by_priorities(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, priority="high", published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, priority="low", published_at=now - timedelta(hours=1))

    response = client.get(
        "/api/bulletin/preview-count", params={"priorities": "high"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_preview_count_include_favorites_unions_with_priorities(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, priority="high", is_starred=False, published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, priority="low", is_starred=True, published_at=now - timedelta(hours=1))
    _make_article(db_session, feed.id, priority="med", is_starred=False, published_at=now - timedelta(hours=1))

    response = client.get(
        "/api/bulletin/preview-count",
        params={"priorities": "high", "include_favorites": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"count": 2}


def test_preview_count_dedup_when_overlapping(client, auth_headers, db_session):
    """A naive 'count matches + count starred' implementation would double-count
    an article that satisfies both — the real union must count it once."""
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, priority="high", is_starred=True, published_at=now - timedelta(hours=1))

    response = client.get(
        "/api/bulletin/preview-count",
        params={"priorities": "high", "include_favorites": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_preview_count_rejects_invalid_priority(client, auth_headers):
    response = client.get(
        "/api/bulletin/preview-count", params={"priorities": "urgent"}, headers=auth_headers
    )
    assert response.status_code == 400


def test_preview_count_zero_when_no_matches(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, priority="low", published_at=now - timedelta(hours=1))

    response = client.get(
        "/api/bulletin/preview-count", params={"priorities": "high"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {"count": 0}


def test_preview_count_works_without_categories(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, published_at=now - timedelta(hours=1))

    response = client.get("/api/bulletin/preview-count", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"count": 1}


# ==================== POST /generate — template artifact regressions ====================

def test_generate_bulletin_no_blank_heading1_paragraphs(client, auth_headers, db_session, monkeypatch):
    """The bundled template contains several empty Heading1 paragraphs used as
    layout spacers (a Google Docs export artifact). An earlier version of the
    stray-heading cleanup keyed template headings by normalized text in a
    dict, so multiple blank headings collided under the same '' key and all
    but one silently survived un-removed in the output — orphaned blank
    Heading1 paragraphs that broke Word's İçindekiler (Table of Contents)
    generation on open."""
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    # A category name unrelated to the template's own defaults forces every
    # bundled Heading1 (including its blank spacers) through the stray-removal path.
    _make_bulletin_category(db_session, name="Teknoloji")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Yapay Zeka Haberi", published_at=now - timedelta(hours=1))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    document = DocxDocument(io.BytesIO(response.content))
    blank_heading1s = [
        p for p in document.paragraphs if p.style.style_id == "Heading1" and not p.text.strip()
    ]
    assert blank_heading1s == []


def test_generate_bulletin_update_fields_precedes_compat_in_settings(client, auth_headers, db_session, monkeypatch):
    """word/settings.xml's CT_Settings content model is a strict, ordered
    sequence. updateFields was previously inserted as the very first child,
    ahead of elements the schema requires first (embedTrueTypeFonts,
    defaultTabStop) — an out-of-order settings.xml that Word's settings
    parser can reject or silently repair. It must be positioned immediately
    before w:compat."""
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Test Haberi", published_at=now - timedelta(hours=1))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        settings_xml = zf.read("word/settings.xml").decode("utf-8")
    update_fields_idx = settings_xml.index("<w:updateFields")
    # Must come after elements the schema requires first (an earlier version
    # inserted updateFields as the very first child of <w:settings>, ahead of
    # these) and before w:compat.
    assert settings_xml.index("<w:defaultTabStop") < update_fields_idx
    assert update_fields_idx < settings_xml.index("<w:compat")


def test_generate_bulletin_toc_field_is_locale_independent(client, auth_headers, db_session, monkeypatch):
    """The bundled template's TOC field originally selected entries purely
    via \\t, a literal English-only style-name list ("Heading 1,1,Heading
    2,2,..."). \\t matches a paragraph by its LOCALIZED style display name,
    and Word does not translate "Heading 1" for that comparison on a
    non-English install (confirmed via Word COM automation on a German
    installation: the paragraph's outline level was correctly 1, but its
    style name is "Überschrift 1", so \\t alone matched nothing and the TOC
    came back with zero entries) — reproducing exactly the "no heading style
    applied" dialog reported against a real generated bulletin. \\o "1-6"
    additionally matches by outline level, which is locale-independent."""
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Test Haberi", published_at=now - timedelta(hours=1))

    response = client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    toc_instr_start = document_xml.index("<w:instrText")
    toc_instr_end = document_xml.index("</w:instrText>", toc_instr_start)
    # instrText may be split across sibling elements; the TOC's own opening
    # instrText run is the first one in the document (inside the bundled
    # İçindekiler content control), so this is enough to check its content.
    toc_instr_text = document_xml[toc_instr_start:toc_instr_end]
    assert "TOC" in toc_instr_text
    assert '\\o "1-6"' in toc_instr_text or "\\o &quot;1-6&quot;" in toc_instr_text


# ==================== Generated Bulletin Persistence ====================

def test_generate_bulletin_persists_a_row(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Test Haberi", priority="high", published_at=now - timedelta(hours=1))

    response = client.post(
        "/api/bulletin/generate",
        json={"priorities": ["high"], "include_favorites": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    rows = crud.get_generated_bulletins(db_session)
    assert len(rows) == 1
    row = rows[0]
    assert row.article_count == 1
    assert row.priorities == "high"
    assert row.include_favorites is True
    assert Path(row.stored_path).exists()


def test_list_generated_bulletins_requires_auth(client):
    response = client.get("/api/bulletin/generated")
    assert response.status_code == 401


def test_list_generated_bulletins_returns_newest_first(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Birinci", published_at=now - timedelta(hours=1))
    client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    _make_article(db_session, feed.id, title="Ikinci", published_at=now - timedelta(hours=1))
    client.post("/api/bulletin/generate", json={}, headers=auth_headers)

    response = client.get("/api/bulletin/generated", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["article_count"] == 2  # most recent generate saw both articles
    assert body[1]["article_count"] == 1


def test_download_generated_bulletin_requires_auth(client):
    response = client.get("/api/bulletin/generated/1/download")
    assert response.status_code == 401


def test_download_generated_bulletin_404_when_missing(client, auth_headers):
    response = client.get("/api/bulletin/generated/999999/download", headers=auth_headers)
    assert response.status_code == 404


def test_download_generated_bulletin_returns_the_saved_file(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Test Haberi", published_at=now - timedelta(hours=1))
    client.post("/api/bulletin/generate", json={}, headers=auth_headers)
    bulletin_id = crud.get_generated_bulletins(db_session)[0].id

    response = client.get(f"/api/bulletin/generated/{bulletin_id}/download", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert response.content[:4] == b"PK\x03\x04"


def test_delete_generated_bulletin_requires_auth(client):
    response = client.delete("/api/bulletin/generated/1")
    assert response.status_code == 401


def test_delete_generated_bulletin_404_when_missing(client, auth_headers):
    response = client.delete("/api/bulletin/generated/999999", headers=auth_headers)
    assert response.status_code == 404


def test_delete_generated_bulletin_removes_row_and_file(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", _fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_digest", _fake_digest)

    _make_bulletin_category(db_session, name="AVRUPA")
    feed = _make_feed(db_session)
    now = datetime.now(timezone.utc)
    _make_article(db_session, feed.id, title="Test Haberi", published_at=now - timedelta(hours=1))
    client.post("/api/bulletin/generate", json={}, headers=auth_headers)
    row = crud.get_generated_bulletins(db_session)[0]
    stored_path = Path(row.stored_path)
    assert stored_path.exists()

    response = client.delete(f"/api/bulletin/generated/{row.id}", headers=auth_headers)

    assert response.status_code == 200
    assert crud.get_generated_bulletin(db_session, row.id) is None
    assert not stored_path.exists()
