"""
Tests for app/api/routes/articles.py — every endpoint except the
priority-scoped bulk delete/archive routes, plus the unimportant-scoped
bulk routes, listing/filtering, read/star toggles, counts, and detail views.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db import models, crud
from tests.conftest import (
    _make_feed, _make_article, _make_topic, _make_article_topic, _make_summary,
    _make_bulletin_classification,
)


def test_delete_all_by_priority_requires_auth(client):
    response = client.post("/api/articles/priority/high/delete-all")
    assert response.status_code == 401


def test_delete_all_by_priority_rejects_invalid_priority(client, admin_headers):
    response = client.post("/api/articles/priority/urgent/delete-all", headers=admin_headers)
    assert response.status_code == 400


def test_archive_all_by_priority_rejects_invalid_priority(client, auth_headers):
    response = client.post("/api/articles/priority/urgent/archive-all", headers=auth_headers)
    assert response.status_code == 400


def test_delete_all_by_priority_deletes_only_matching_unread_articles(client, admin_headers, db_session):
    feed = _make_feed(db_session)
    to_delete_1 = _make_article(db_session, feed.id, priority="high", is_read=False)
    to_delete_2 = _make_article(db_session, feed.id, priority="high", is_read=False)
    other_priority = _make_article(db_session, feed.id, priority="low", is_read=False)
    already_read = _make_article(db_session, feed.id, priority="high", is_read=True)

    response = client.post("/api/articles/priority/high/delete-all", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 2}
    remaining_ids = {a.id for a in db_session.query(models.Article).all()}
    assert to_delete_1.id not in remaining_ids
    assert to_delete_2.id not in remaining_ids
    assert other_priority.id in remaining_ids
    assert already_read.id in remaining_ids


def test_archive_all_by_priority_marks_matching_unread_as_read(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    a1 = _make_article(db_session, feed.id, priority="med", is_read=False)
    a2 = _make_article(db_session, feed.id, priority="med", is_read=False)
    other_priority = _make_article(db_session, feed.id, priority="low", is_read=False)

    response = client.post("/api/articles/priority/med/archive-all", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"archived_count": 2}
    db_session.refresh(a1)
    db_session.refresh(a2)
    db_session.refresh(other_priority)
    assert a1.is_read is True
    assert a2.is_read is True
    assert other_priority.is_read is False


def test_delete_all_by_priority_scopes_to_feed_ids(client, admin_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    in_scope = _make_article(db_session, feed_a.id, priority="high", is_read=False)
    out_of_scope = _make_article(db_session, feed_b.id, priority="high", is_read=False)

    response = client.post(
        "/api/articles/priority/high/delete-all",
        params={"feed_ids": str(feed_a.id)},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    remaining_ids = {a.id for a in db_session.query(models.Article).all()}
    assert in_scope.id not in remaining_ids
    assert out_of_scope.id in remaining_ids


# ==================== DELETE /{article_id} ====================

def test_delete_article_requires_auth(client):
    response = client.delete("/api/articles/1")
    assert response.status_code == 401


def test_delete_article_success_returns_204_and_tombstones_url(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, url="https://example.com/to-delete")

    response = client.delete(f"/api/articles/{article.id}", headers=auth_headers)

    assert response.status_code == 204
    assert db_session.query(models.Article).filter(models.Article.id == article.id).first() is None
    assert "https://example.com/to-delete" in crud.get_deleted_urls(db_session)


def test_delete_article_that_is_in_a_bulletin_succeeds(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_bulletin_classification(db_session, article.id)

    response = client.delete(f"/api/articles/{article.id}", headers=auth_headers)

    assert response.status_code == 204
    assert db_session.query(models.ArticleBulletinClassification).count() == 0


def test_bulk_deletes_remove_articles_that_are_in_a_bulletin(db_session):
    feed = _make_feed(db_session)
    high = _make_article(db_session, feed.id, priority="high", importance="important")
    unimportant = _make_article(db_session, feed.id, importance="unimportant")
    _make_bulletin_classification(db_session, high.id)
    _make_bulletin_classification(db_session, unimportant.id)

    assert crud.delete_articles_by_priority(db_session, "high") == 1
    assert crud.delete_articles_unimportant(db_session) == 1
    assert db_session.query(models.ArticleBulletinClassification).count() == 0


def test_delete_feed_removes_its_bulletin_classified_articles(db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_bulletin_classification(db_session, article.id)

    assert crud.delete_feed(db_session, feed.id) is True
    assert db_session.query(models.Article).count() == 0
    assert db_session.query(models.ArticleBulletinClassification).count() == 0


def test_delete_article_404_when_missing(client, auth_headers):
    response = client.delete("/api/articles/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


# ==================== GET / (list_articles) ====================

def test_list_articles_requires_auth(client):
    response = client.get("/api/articles/")
    assert response.status_code == 401


def test_list_articles_default_orders_by_published_desc(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    oldest = _make_article(db_session, feed.id, url="https://example.com/old",
                            published_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    newest = _make_article(db_session, feed.id, url="https://example.com/new",
                            published_at=datetime(2024, 3, 1, tzinfo=timezone.utc))
    middle = _make_article(db_session, feed.id, url="https://example.com/mid",
                            published_at=datetime(2024, 2, 1, tzinfo=timezone.utc))

    response = client.get("/api/articles/", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert [a["id"] for a in body["articles"]] == [newest.id, middle.id, oldest.id]


def test_list_articles_published_at_round_trips_as_utc(client, auth_headers, db_session):
    """Regression test: a non-UTC published_at must come back from the API as
    explicit UTC, not a naive/local-ambiguous string (see UTCDateTime in
    app/db/database.py) — otherwise the frontend can render it as being in the
    future ("... sonra") depending on the browser's timezone."""
    feed = _make_feed(db_session)
    cest = timezone(timedelta(hours=2))
    _make_article(db_session, feed.id, url="https://example.com/cest",
                   published_at=datetime(2026, 9, 13, 12, 47, tzinfo=cest))

    response = client.get("/api/articles/", headers=auth_headers)

    assert response.status_code == 200
    published_at = response.json()["articles"][0]["published_at"]
    assert published_at.endswith("+00:00") or published_at.endswith("Z")
    parsed = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    assert parsed == datetime(2026, 9, 13, 10, 47, tzinfo=timezone.utc)


def test_list_articles_includes_image_url(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, image_url="https://static.dw.com/image/12345.jpg")
    _make_article(db_session, feed.id, image_url=None)

    response = client.get("/api/articles/", headers=auth_headers)

    assert response.status_code == 200
    image_urls = {a["image_url"] for a in response.json()["articles"]}
    assert image_urls == {"https://static.dw.com/image/12345.jpg", None}


def test_get_article_includes_image_url(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, image_url="https://static.dw.com/image/67890.jpg")

    response = client.get(f"/api/articles/{article.id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["image_url"] == "https://static.dw.com/image/67890.jpg"


def test_list_articles_limit_over_100_returns_422(client, auth_headers):
    response = client.get("/api/articles/", params={"limit": 101}, headers=auth_headers)
    assert response.status_code == 422


def test_list_articles_limit_under_1_returns_422(client, auth_headers):
    response = client.get("/api/articles/", params={"limit": 0}, headers=auth_headers)
    assert response.status_code == 422


def test_list_articles_negative_skip_returns_422(client, auth_headers):
    response = client.get("/api/articles/", params={"skip": -1}, headers=auth_headers)
    assert response.status_code == 422


def test_list_articles_filters_by_topic_ids(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Politics")
    linked = _make_article(db_session, feed.id, url="https://example.com/linked")
    unlinked = _make_article(db_session, feed.id, url="https://example.com/unlinked")
    _make_article_topic(db_session, linked.id, topic.id)

    response = client.get("/api/articles/", params={"topic_ids": str(topic.id)}, headers=auth_headers)

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()["articles"]}
    assert ids == {linked.id}


def test_list_articles_rejects_malformed_topic_ids(client, auth_headers):
    response = client.get("/api/articles/", params={"topic_ids": "1,abc"}, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid topic IDs format"


def test_list_articles_rejects_malformed_feed_ids(client, auth_headers):
    response = client.get("/api/articles/", params={"feed_ids": "1,abc"}, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid feed IDs format"


def test_list_articles_search_matches_title_or_content(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    title_match = _make_article(db_session, feed.id, url="https://example.com/a1",
                                 title="Quantum computing breakthrough")
    content_match = _make_article(db_session, feed.id, url="https://example.com/a2",
                                   title="Unrelated headline", cleaned_content="...quantum details...")
    no_match = _make_article(db_session, feed.id, url="https://example.com/a3",
                              title="Other news", cleaned_content="nothing relevant")

    response = client.get("/api/articles/", params={"search": "quantum"}, headers=auth_headers)

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()["articles"]}
    assert ids == {title_match.id, content_match.id}
    assert no_match.id not in ids


def test_list_articles_search_matches_word_starts_not_substrings(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    upper = _make_article(db_session, feed.id, url="https://example.com/w1", title="NATO summit opens")
    compound = _make_article(db_session, feed.id, url="https://example.com/w2", title="Nato-Gipfel in Den Haag")
    in_content = _make_article(db_session, feed.id, url="https://example.com/w3", title="Defence news",
                               cleaned_content="Leaders of the (Nato) alliance met.")
    # "nato" only appears inside other words — must not match
    donations = _make_article(db_session, feed.id, url="https://example.com/w4", title="Farage's donations plan")
    senator = _make_article(db_session, feed.id, url="https://example.com/w5", title="Other",
                            cleaned_content="The senator spoke.")

    response = client.get("/api/articles/", params={"search": "nato"}, headers=auth_headers)

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()["articles"]}
    assert ids == {upper.id, compound.id, in_content.id}
    assert donations.id not in ids and senator.id not in ids


def test_list_articles_search_matches_word_prefixes_and_turkish_letters(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    quantum = _make_article(db_session, feed.id, url="https://example.com/p1", title="Quantum leap")
    turkiye = _make_article(db_session, feed.id, url="https://example.com/p2", title="Türkiye ve AB")
    _make_article(db_session, feed.id, url="https://example.com/p3", title="Unrelated")

    by_prefix = client.get("/api/articles/", params={"search": "quant"}, headers=auth_headers)
    by_turkish = client.get("/api/articles/", params={"search": "türk"}, headers=auth_headers)

    assert {a["id"] for a in by_prefix.json()["articles"]} == {quantum.id}
    assert {a["id"] for a in by_turkish.json()["articles"]} == {turkiye.id}


def test_list_articles_search_treats_regex_characters_literally(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    cpp = _make_article(db_session, feed.id, url="https://example.com/r1", title="C++ (update) released")
    _make_article(db_session, feed.id, url="https://example.com/r2", title="Cats released")

    response = client.get("/api/articles/", params={"search": "c++ (update"}, headers=auth_headers)

    assert response.status_code == 200
    assert {a["id"] for a in response.json()["articles"]} == {cpp.id}


def test_list_articles_feed_ids_takes_precedence_over_feed_id(client, auth_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    article_a = _make_article(db_session, feed_a.id, url="https://example.com/article-a")
    article_b = _make_article(db_session, feed_b.id, url="https://example.com/article-b")

    response = client.get(
        "/api/articles/",
        params={"feed_id": feed_b.id, "feed_ids": str(feed_a.id)},
        headers=auth_headers,
    )

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()["articles"]}
    assert ids == {article_a.id}


def test_list_articles_filters_by_is_read_and_is_starred(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    unread_unstarred = _make_article(db_session, feed.id, url="https://example.com/u1",
                                      is_read=False, is_starred=False)
    unread_starred = _make_article(db_session, feed.id, url="https://example.com/u2",
                                    is_read=False, is_starred=True)
    read_starred = _make_article(db_session, feed.id, url="https://example.com/u3",
                                  is_read=True, is_starred=True)

    response = client.get(
        "/api/articles/",
        params={"is_read": "false", "is_starred": "true"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    ids = {a["id"] for a in response.json()["articles"]}
    assert ids == {unread_starred.id}


# ==================== PATCH /{article_id}/read, POST /mark-read-bulk ====================

def test_mark_article_read_success_and_idempotent(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)

    first = client.patch(f"/api/articles/{article.id}/read", headers=auth_headers)
    second = client.patch(f"/api/articles/{article.id}/read", headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {"id": article.id, "is_read": True}
    assert second.status_code == 200
    assert second.json() == {"id": article.id, "is_read": True}


def test_mark_article_read_404_when_missing(client, auth_headers):
    response = client.patch("/api/articles/999999/read", headers=auth_headers)
    assert response.status_code == 404


def test_mark_read_bulk_requires_article_ids_or_mark_all(client, auth_headers):
    response = client.post("/api/articles/mark-read-bulk", json={}, headers=auth_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Provide article_ids or set mark_all=true"


def test_mark_read_bulk_by_article_ids_only_counts_unread(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    a1 = _make_article(db_session, feed.id, url="https://example.com/b1", is_read=False)
    a2 = _make_article(db_session, feed.id, url="https://example.com/b2", is_read=False)
    already_read = _make_article(db_session, feed.id, url="https://example.com/b3", is_read=True)

    response = client.post(
        "/api/articles/mark-read-bulk",
        json={"article_ids": [a1.id, a2.id, already_read.id]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"marked_count": 2}


def test_mark_read_bulk_mark_all_wins_over_article_ids(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    outside_list = _make_article(db_session, feed.id, url="https://example.com/c1", is_read=False)
    in_list_1 = _make_article(db_session, feed.id, url="https://example.com/c2", is_read=False)
    in_list_2 = _make_article(db_session, feed.id, url="https://example.com/c3", is_read=False)

    response = client.post(
        "/api/articles/mark-read-bulk",
        json={"article_ids": [in_list_1.id, in_list_2.id], "mark_all": True},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"marked_count": 3}
    db_session.refresh(outside_list)
    assert outside_list.is_read is True


def test_mark_read_bulk_rejects_malformed_topic_ids_in_body(client, auth_headers):
    response = client.post(
        "/api/articles/mark-read-bulk",
        json={"mark_all": True, "topic_ids": "1,abc"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid topic IDs format"


def test_mark_read_bulk_rejects_malformed_feed_ids_in_body(client, auth_headers):
    response = client.post(
        "/api/articles/mark-read-bulk",
        json={"mark_all": True, "feed_ids": "1,abc"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid feed IDs format"


# ==================== PATCH /{article_id}/star, POST /unstar-all ====================

def test_star_article_defaults_to_true_with_empty_body(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, is_starred=False)

    response = client.patch(f"/api/articles/{article.id}/star", json={}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"id": article.id, "is_starred": True}
    db_session.refresh(article)
    assert article.is_starred is True


def test_star_article_can_unstar(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, is_starred=True)

    response = client.patch(
        f"/api/articles/{article.id}/star", json={"starred": False}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json() == {"id": article.id, "is_starred": False}
    db_session.refresh(article)
    assert article.is_starred is False


def test_star_article_404_when_missing(client, auth_headers):
    response = client.patch("/api/articles/999999/star", json={}, headers=auth_headers)
    assert response.status_code == 404


def test_unstar_all_only_clears_previously_starred(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    starred_1 = _make_article(db_session, feed.id, url="https://example.com/s1", is_starred=True)
    starred_2 = _make_article(db_session, feed.id, url="https://example.com/s2", is_starred=True)
    not_starred = _make_article(db_session, feed.id, url="https://example.com/s3", is_starred=False)

    response = client.post("/api/articles/unstar-all", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"unstarred_count": 2}
    for article in (starred_1, starred_2, not_starred):
        db_session.refresh(article)
        assert article.is_starred is False


# ==================== GET /topic/{topic_id}/ids ====================

def test_get_article_ids_by_topic_404_when_topic_missing(client, auth_headers):
    response = client.get("/api/articles/topic/999999/ids", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Topic not found"


def test_get_article_ids_by_topic_returns_all_regardless_of_status(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Economy")
    read_article = _make_article(db_session, feed.id, url="https://example.com/r1", is_read=True)
    unread_article = _make_article(db_session, feed.id, url="https://example.com/r2", is_read=False)
    _make_article_topic(db_session, read_article.id, topic.id)
    _make_article_topic(db_session, unread_article.id, topic.id)

    response = client.get(f"/api/articles/topic/{topic.id}/ids", headers=auth_headers)

    assert response.status_code == 200
    assert set(response.json()["article_ids"]) == {read_article.id, unread_article.id}


# ==================== POST /unimportant/delete-all, /unimportant/archive-all ====================

def test_delete_unimportant_scopes_to_importance_and_unread(client, admin_headers, db_session):
    feed = _make_feed(db_session)
    to_delete = _make_article(db_session, feed.id, url="https://example.com/d1",
                               importance="unimportant", is_read=False)
    read_unimportant = _make_article(db_session, feed.id, url="https://example.com/d2",
                                      importance="unimportant", is_read=True)
    important = _make_article(db_session, feed.id, url="https://example.com/d3",
                               importance="important", is_read=False)
    unset = _make_article(db_session, feed.id, url="https://example.com/d4",
                           importance=None, is_read=False)

    response = client.post("/api/articles/unimportant/delete-all", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    remaining_ids = {a.id for a in db_session.query(models.Article).all()}
    assert to_delete.id not in remaining_ids
    assert {read_unimportant.id, important.id, unset.id}.issubset(remaining_ids)


def test_delete_unimportant_scopes_to_feed_ids(client, admin_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    in_scope = _make_article(db_session, feed_a.id, url="https://example.com/e1",
                              importance="unimportant", is_read=False)
    out_of_scope = _make_article(db_session, feed_b.id, url="https://example.com/e2",
                                  importance="unimportant", is_read=False)

    response = client.post(
        "/api/articles/unimportant/delete-all",
        params={"feed_ids": str(feed_a.id)},
        headers=admin_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    remaining_ids = {a.id for a in db_session.query(models.Article).all()}
    assert in_scope.id not in remaining_ids
    assert out_of_scope.id in remaining_ids


def test_archive_unimportant_marks_matching_read_only(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    to_archive = _make_article(db_session, feed.id, url="https://example.com/f1",
                                importance="unimportant", is_read=False)
    important = _make_article(db_session, feed.id, url="https://example.com/f2",
                               importance="important", is_read=False)

    response = client.post("/api/articles/unimportant/archive-all", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"archived_count": 1}
    db_session.refresh(to_archive)
    db_session.refresh(important)
    assert to_archive.is_read is True
    assert important.is_read is False
    assert db_session.query(models.Article).filter(models.Article.id == to_archive.id).first() is not None


# ==================== GET /counts ====================

def test_get_article_counts_by_priority_excludes_read_and_null_priority(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, url="https://example.com/g1", priority="high", is_read=False)
    _make_article(db_session, feed.id, url="https://example.com/g2", priority="high", is_read=True)
    _make_article(db_session, feed.id, url="https://example.com/g3", priority=None, is_read=False)

    response = client.get("/api/articles/counts", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["by_priority"] == {"high": 1}


def test_get_counts_by_feed_excludes_read_articles(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, url="https://example.com/h1", is_read=True)
    _make_article(db_session, feed.id, url="https://example.com/h2", is_read=False)

    response = client.get("/api/articles/counts", headers=auth_headers)

    assert response.status_code == 200
    # Only the unread article counts toward the feed total.
    assert response.json()["by_feed"][str(feed.id)] == 1


def test_get_counts_by_feed_omits_feed_with_only_read_articles(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, url="https://example.com/j1", is_read=True)

    response = client.get("/api/articles/counts", headers=auth_headers)

    assert response.status_code == 200
    # A feed whose articles are all read is absent from by_feed (grouped count of 0).
    assert str(feed.id) not in response.json()["by_feed"]


def test_get_article_counts_unread_read_starred_totals(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, url="https://example.com/i1", is_read=False, is_starred=False)
    _make_article(db_session, feed.id, url="https://example.com/i2", is_read=False, is_starred=True)
    _make_article(db_session, feed.id, url="https://example.com/i3", is_read=True, is_starred=False)
    _make_article(db_session, feed.id, url="https://example.com/i4", is_read=False,
                  importance="unimportant")

    response = client.get("/api/articles/counts", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["unread_count"] == 3
    assert body["read_count"] == 1
    assert body["starred_count"] == 1
    assert body["unimportant_count"] == 1


# ==================== GET /{article_id} (detail) ====================

def test_get_article_detail_returns_content_and_topics(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Science")
    article = _make_article(db_session, feed.id, raw_content="<p>raw</p>", cleaned_content="cleaned")
    _make_article_topic(db_session, article.id, topic.id)
    _make_summary(db_session, article.id)

    response = client.get(f"/api/articles/{article.id}", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["raw_content"] == "<p>raw</p>"
    assert body["cleaned_content"] == "cleaned"
    assert body["has_summaries"] is True
    assert [t["id"] for t in body["topics"]] == [topic.id]


def test_get_article_detail_404_when_missing(client, auth_headers):
    response = client.get("/api/articles/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


# ==================== GET /topic/{topic_name} ====================

def test_get_articles_by_topic_name_returns_list(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Politics")
    article = _make_article(db_session, feed.id)
    _make_article_topic(db_session, article.id, topic.id)

    response = client.get("/api/articles/topic/Politics", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"articles", "total", "skip", "limit"}
    assert body["total"] == 1
    assert body["articles"][0]["id"] == article.id


def test_get_articles_by_topic_name_404_when_missing(client, auth_headers):
    response = client.get("/api/articles/topic/Nonexistent", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Topic not found"


def test_get_articles_by_topic_name_is_case_sensitive(client, auth_headers, db_session):
    _make_topic(db_session, name="Politics")

    response = client.get("/api/articles/topic/politics", headers=auth_headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# "Error" group: articles that never received a severity label
# ---------------------------------------------------------------------------

def _error_fixture(db_session):
    """One article per relevant state; returns (feed, {name: article})."""
    feed = _make_feed(db_session)
    arts = {
        "error": _make_article(db_session, feed.id, title="err", status="summarized"),
        "error_failed": _make_article(db_session, feed.id, title="err-failed", status="failed"),
        "error_no_priority": _make_article(db_session, feed.id, title="err-imp", importance="important",
                                           status="summarized"),
        "high": _make_article(db_session, feed.id, title="high", importance="important",
                              priority="high", status="summarized"),
        "unimportant": _make_article(db_session, feed.id, title="unimp", importance="unimportant",
                                     status="filtered"),
        "pending": _make_article(db_session, feed.id, title="pending", status="pending"),
        "scraped": _make_article(db_session, feed.id, title="scraped", status="scraped"),
    }
    return feed, arts


def test_list_articles_is_error_returns_only_unlabelled_articles(client, auth_headers, db_session):
    _, arts = _error_fixture(db_session)

    resp = client.get("/api/articles/?is_error=true", headers=auth_headers)

    assert resp.status_code == 200
    body = resp.json()
    titles = {a["title"] for a in body["articles"]}
    # Önemsiz (importance=unimportant), labelled and still-processing articles are not errors.
    assert titles == {"err", "err-failed", "err-imp"}
    assert body["total"] == 3


def test_list_articles_without_is_error_still_returns_everything(client, auth_headers, db_session):
    _, arts = _error_fixture(db_session)

    resp = client.get("/api/articles/", headers=auth_headers)

    assert resp.json()["total"] == len(arts)


def test_article_counts_include_error_count(client, auth_headers, db_session):
    _error_fixture(db_session)

    resp = client.get("/api/articles/counts", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["error_count"] == 3


def test_mark_read_bulk_mark_all_scoped_to_is_error(client, auth_headers, db_session):
    _, arts = _error_fixture(db_session)

    resp = client.post("/api/articles/mark-read-bulk",
                       json={"mark_all": True, "is_error": True}, headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json()["marked_count"] == 3
    db_session.expire_all()
    assert arts["error"].is_read is True
    assert arts["high"].is_read is False
    assert arts["unimportant"].is_read is False


def test_reprocess_requires_auth(client):
    assert client.post("/api/articles/reprocess", json={"all_errors": True}).status_code == 401
    assert client.get("/api/articles/reprocess-status").status_code == 401


def test_reprocess_requires_article_ids_or_all_errors(client, admin_headers):
    resp = client.post("/api/articles/reprocess", json={}, headers=admin_headers)
    assert resp.status_code == 400


@pytest.fixture
def captured_reprocess(monkeypatch):
    """Replace the background job so route tests never hit OpenAI; records queued ids."""
    from app.tasks import background
    calls = []

    async def fake_task(ids):
        calls.append(list(ids))

    monkeypatch.setattr(background, "reprocess_articles_task", fake_task)
    monkeypatch.setattr(background, "register_reprocess", lambda n: None)
    return calls


def test_reprocess_single_article_queues_it_and_leaves_error_group(
        client, admin_headers, db_session, captured_reprocess):
    _, arts = _error_fixture(db_session)

    resp = client.post("/api/articles/reprocess",
                       json={"article_ids": [arts["error"].id]}, headers=admin_headers)

    assert resp.status_code == 200
    assert resp.json()["queued"] == 1
    assert captured_reprocess == [[arts["error"].id]]
    db_session.expire_all()
    assert arts["error"].status == "pending"
    assert client.get("/api/articles/counts", headers=admin_headers).json()["error_count"] == 2


def test_reprocess_registers_run_on_the_event_loop(client, admin_headers, db_session, monkeypatch):
    """Regression: the route is a sync `def` (threadpool), but `_reprocess_status` is also mutated
    by `reprocess_articles_task` on the event loop. Registering from the worker thread could
    interleave with the task's final `status = "done"` and strand the new articles' progress."""
    import asyncio
    from app.tasks import background
    _, arts = _error_fixture(db_session)
    on_loop = []

    async def fake_task(ids):
        pass

    def recording_register(count):
        try:
            asyncio.get_running_loop()
            on_loop.append(True)
        except RuntimeError:
            on_loop.append(False)

    monkeypatch.setattr(background, "reprocess_articles_task", fake_task)
    monkeypatch.setattr(background, "register_reprocess", recording_register)

    resp = client.post("/api/articles/reprocess",
                       json={"article_ids": [arts["error"].id]}, headers=admin_headers)

    assert resp.status_code == 200
    assert on_loop == [True]


def test_reprocess_ignores_articles_that_are_not_errors(
        client, admin_headers, db_session, captured_reprocess):
    _, arts = _error_fixture(db_session)

    resp = client.post(
        "/api/articles/reprocess",
        json={"article_ids": [arts["high"].id, arts["unimportant"].id, arts["error_failed"].id]},
        headers=admin_headers,
    )

    assert resp.json()["queued"] == 1
    assert captured_reprocess == [[arts["error_failed"].id]]
    db_session.expire_all()
    assert arts["high"].status == "summarized"
    assert arts["unimportant"].status == "filtered"


def test_reprocess_all_errors_bulk_and_scoped_to_feed(
        client, admin_headers, db_session, captured_reprocess):
    feed, arts = _error_fixture(db_session)
    other_feed = _make_feed(db_session, url="https://example.com/other")
    other = _make_article(db_session, other_feed.id, title="other-err", status="summarized")

    resp = client.post("/api/articles/reprocess",
                       json={"all_errors": True, "feed_ids": [other_feed.id]}, headers=admin_headers)
    assert resp.json()["article_ids"] == [other.id]

    resp = client.post("/api/articles/reprocess", json={"all_errors": True}, headers=admin_headers)
    assert resp.json()["queued"] == 3  # `other` is already pending; the 3 in `feed` remain


def test_reprocess_with_nothing_to_do_queues_nothing(
        client, admin_headers, db_session, captured_reprocess):
    _, arts = _error_fixture(db_session)

    resp = client.post("/api/articles/reprocess",
                       json={"article_ids": [arts["high"].id]}, headers=admin_headers)

    assert resp.json() == {"queued": 0, "article_ids": []}
    assert captured_reprocess == []


def test_reprocess_status_endpoint_reports_idle_shape(client, auth_headers):
    resp = client.get("/api/articles/reprocess-status", headers=auth_headers)

    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "total", "done", "failed"}


def test_counts_exclude_error_articles_from_unread_and_by_feed(client, auth_headers, db_session):
    feed, arts = _error_fixture(db_session)

    body = client.get("/api/articles/counts", headers=auth_headers).json()

    # 3 errors are excluded; unread = high + unimportant + pending + scraped
    assert body["unread_count"] == 4
    assert body["by_feed"][str(feed.id)] == 4
    assert body["error_count"] == 3


def test_list_is_error_false_excludes_error_articles(client, auth_headers, db_session):
    _, arts = _error_fixture(db_session)

    resp = client.get("/api/articles/?is_error=false&is_read=false", headers=auth_headers)

    titles = {a["title"] for a in resp.json()["articles"]}
    assert titles == {"high", "unimp", "pending", "scraped"}
    assert resp.json()["total"] == 4


def test_mark_all_read_from_unread_tab_leaves_error_articles_unread(client, auth_headers, db_session):
    _, arts = _error_fixture(db_session)

    resp = client.post("/api/articles/mark-read-bulk",
                       json={"mark_all": True, "is_read": False, "is_error": False}, headers=auth_headers)

    assert resp.json()["marked_count"] == 4
    db_session.expire_all()
    assert arts["error"].is_read is False and arts["error_failed"].is_read is False
    assert arts["high"].is_read is True


def test_topic_unread_count_excludes_error_articles(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, "Politik")
    ok = _make_article(db_session, feed.id, importance="important", priority="high", status="summarized")
    err = _make_article(db_session, feed.id, status="summarized", importance="important")
    _make_article_topic(db_session, ok.id, topic.id)
    _make_article_topic(db_session, err.id, topic.id)

    body = client.get("/api/topics/", headers=auth_headers).json()

    assert body[0]["article_count"] == 2
    assert body[0]["unread_count"] == 1


def _labelled_failed(db_session):
    """Labelled (Yüksek) article whose summarization failed -> status "failed"."""
    feed = _make_feed(db_session)
    ok = _make_article(db_session, feed.id, title="ok-high", importance="important",
                       priority="high", status="summarized")
    failed = _make_article(db_session, feed.id, title="high-no-summary", importance="important",
                           priority="high", status="failed")
    return feed, ok, failed


def test_labelled_but_failed_article_is_an_error_article(client, auth_headers, db_session):
    """Regression: a labelled article left `failed` (no summary) had no retry path because the
    Error group only contained unlabelled articles."""
    _, ok, failed = _labelled_failed(db_session)

    listed = client.get("/api/articles/?is_error=true", headers=auth_headers).json()

    assert [a["id"] for a in listed["articles"]] == [failed.id]
    assert client.get("/api/articles/counts", headers=auth_headers).json()["error_count"] == 1


def test_labelled_failed_article_is_excluded_from_unread_and_priority_counts(client, auth_headers, db_session):
    _labelled_failed(db_session)

    body = client.get("/api/articles/counts", headers=auth_headers).json()

    assert body["unread_count"] == 1
    assert body["by_priority"] == {"high": 1}


def test_reprocess_accepts_labelled_failed_article(client, admin_headers, db_session, captured_reprocess):
    _, ok, failed = _labelled_failed(db_session)

    resp = client.post("/api/articles/reprocess",
                       json={"article_ids": [ok.id, failed.id]}, headers=admin_headers)

    assert resp.json()["article_ids"] == [failed.id]
    assert captured_reprocess == [[failed.id]]


# ==================== source ("Kaynak") = the article's feed name ====================

def test_article_list_and_detail_return_feed_name_as_source(client, auth_headers, db_session):
    feed = _make_feed(db_session, title="Anadolu Ajansı")
    article = _make_article(db_session, feed.id, author="Burak Bir")

    listed = client.get("/api/articles/", headers=auth_headers).json()["articles"]
    detail = client.get(f"/api/articles/{article.id}", headers=auth_headers).json()

    assert [(a["source"], a["author"]) for a in listed] == [("Anadolu Ajansı", "Burak Bir")]
    assert (detail["source"], detail["author"]) == ("Anadolu Ajansı", "Burak Bir")


def test_article_source_falls_back_to_domain_for_a_feed_without_name(client, auth_headers, db_session):
    feed = _make_feed(db_session, title=None)
    _make_article(db_session, feed.id, url="https://www.dw.com/tr/x")

    listed = client.get("/api/articles/", headers=auth_headers).json()["articles"]

    assert listed[0]["source"] == "dw.com"


# ==================== #37: one filter definition for list / count / mark-read ====================

@pytest.mark.parametrize("filters", [
    {},
    {"priorities": ["high", "med"]},
    {"priority": "low"},
    {"is_starred": True},
    {"is_error": True},
    {"is_error": False, "priorities": ["high"]},
    {"search_query": "NATO"},
])
def test_list_count_and_mark_read_agree_on_the_same_filters(db_session, filters):
    """Regression (#37): the ~40-line filter block was copied three times and had drifted
    (e.g. `priorities` was missing from mark-all-read), so "Tümünü okundu say" could mark a
    different set than the one listed and counted."""
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, title="NATO zirvesi", priority="high", importance="important",
                  status="summarized")
    _make_article(db_session, feed.id, title="Ekonomi", priority="med", importance="important",
                  status="summarized", is_starred=True)
    _make_article(db_session, feed.id, title="Spor", priority="low", importance="important", status="summarized")
    _make_article(db_session, feed.id, title="Hata", status="failed")

    listed = crud.get_articles(db_session, is_read=False, **filters)
    counted = crud.count_articles(db_session, is_read=False, **filters)
    marked = crud.mark_articles_read_bulk(db_session, None, **filters)

    assert len(listed) == counted == marked


def test_counts_endpoint_values(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, priority="high", importance="important", status="summarized")
    _make_article(db_session, feed.id, priority="high", importance="important", status="summarized", is_read=True)
    _make_article(db_session, feed.id, importance="unimportant", status="filtered", is_starred=True)
    _make_article(db_session, feed.id, status="failed")

    body = client.get("/api/articles/counts", headers=auth_headers).json()

    assert body == {
        "by_priority": {"high": 1},
        "by_feed": {str(feed.id): 2},
        "unimportant_count": 1,
        "unread_count": 2,
        "read_count": 1,
        "starred_count": 1,
        "error_count": 1,
    }
