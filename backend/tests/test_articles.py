"""
Tests for app/api/routes/articles.py — every endpoint except the
priority-scoped bulk delete/archive routes, plus the unimportant-scoped
bulk routes, listing/filtering, read/star toggles, counts, and detail views.
"""
from datetime import datetime, timezone

from app.db import models, crud
from tests.conftest import _make_feed, _make_article, _make_topic, _make_article_topic, _make_summary


def test_delete_all_by_priority_requires_auth(client):
    response = client.post("/api/articles/priority/high/delete-all")
    assert response.status_code == 401


def test_delete_all_by_priority_rejects_invalid_priority(client, auth_headers):
    response = client.post("/api/articles/priority/urgent/delete-all", headers=auth_headers)
    assert response.status_code == 400


def test_archive_all_by_priority_rejects_invalid_priority(client, auth_headers):
    response = client.post("/api/articles/priority/urgent/archive-all", headers=auth_headers)
    assert response.status_code == 400


def test_delete_all_by_priority_deletes_only_matching_unread_articles(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    to_delete_1 = _make_article(db_session, feed.id, priority="high", is_read=False)
    to_delete_2 = _make_article(db_session, feed.id, priority="high", is_read=False)
    other_priority = _make_article(db_session, feed.id, priority="low", is_read=False)
    already_read = _make_article(db_session, feed.id, priority="high", is_read=True)

    response = client.post("/api/articles/priority/high/delete-all", headers=auth_headers)

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


def test_delete_all_by_priority_scopes_to_feed_ids(client, auth_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    in_scope = _make_article(db_session, feed_a.id, priority="high", is_read=False)
    out_of_scope = _make_article(db_session, feed_b.id, priority="high", is_read=False)

    response = client.post(
        "/api/articles/priority/high/delete-all",
        params={"feed_ids": str(feed_a.id)},
        headers=auth_headers,
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

def test_delete_unimportant_scopes_to_importance_and_unread(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    to_delete = _make_article(db_session, feed.id, url="https://example.com/d1",
                               importance="unimportant", is_read=False)
    read_unimportant = _make_article(db_session, feed.id, url="https://example.com/d2",
                                      importance="unimportant", is_read=True)
    important = _make_article(db_session, feed.id, url="https://example.com/d3",
                               importance="important", is_read=False)
    unset = _make_article(db_session, feed.id, url="https://example.com/d4",
                           importance=None, is_read=False)

    response = client.post("/api/articles/unimportant/delete-all", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 1}
    remaining_ids = {a.id for a in db_session.query(models.Article).all()}
    assert to_delete.id not in remaining_ids
    assert {read_unimportant.id, important.id, unset.id}.issubset(remaining_ids)


def test_delete_unimportant_scopes_to_feed_ids(client, auth_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    in_scope = _make_article(db_session, feed_a.id, url="https://example.com/e1",
                              importance="unimportant", is_read=False)
    out_of_scope = _make_article(db_session, feed_b.id, url="https://example.com/e2",
                                  importance="unimportant", is_read=False)

    response = client.post(
        "/api/articles/unimportant/delete-all",
        params={"feed_ids": str(feed_a.id)},
        headers=auth_headers,
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
