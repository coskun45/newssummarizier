"""
Tests for the priority-scoped bulk delete/archive routes in
app/api/routes/articles.py (POST /articles/priority/{priority}/delete-all
and /archive-all).
"""
from app.db import models


def _make_feed(db_session, url="https://example.com/feed"):
    feed = models.Feed(url=url, title="Test Feed")
    db_session.add(feed)
    db_session.commit()
    db_session.refresh(feed)
    return feed


def _make_article(db_session, feed_id, *, priority=None, is_read=False, url=None):
    article = models.Article(
        feed_id=feed_id,
        url=url or f"https://example.com/article-{priority}-{is_read}-{id(object())}",
        title="Test Article",
        priority=priority,
        is_read=is_read,
    )
    db_session.add(article)
    db_session.commit()
    db_session.refresh(article)
    return article


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
