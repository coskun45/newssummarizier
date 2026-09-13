"""
Tests for app/api/routes/rss.py (feed CRUD + manual refresh).

`assert_safe_feed_url` (SSRF guard, real DNS lookup) and the background
refresh task are mocked so these tests never touch the network.
"""
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.db import models
from tests.conftest import _make_feed


def _no_op_safe_url():
    return patch("app.api.routes.rss.assert_safe_feed_url", return_value=None)


def _reject_unsafe_url():
    return patch(
        "app.api.routes.rss.assert_safe_feed_url",
        side_effect=HTTPException(status_code=400, detail="Feed URL is not safe"),
    )


# ==================== GET / (list_feeds) ====================

def test_list_feeds_requires_auth(client):
    response = client.get("/api/feeds/")
    assert response.status_code == 401


def test_list_feeds_empty_returns_200(client, auth_headers):
    response = client.get("/api/feeds/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_feeds_active_only_default_excludes_inactive(client, auth_headers, db_session):
    active = _make_feed(db_session, url="https://example.com/active", is_active=True)
    _make_feed(db_session, url="https://example.com/inactive", is_active=False)

    response = client.get("/api/feeds/", headers=auth_headers)

    assert response.status_code == 200
    ids = {f["id"] for f in response.json()}
    assert ids == {active.id}


def test_list_feeds_active_only_false_includes_inactive(client, auth_headers, db_session):
    active = _make_feed(db_session, url="https://example.com/active", is_active=True)
    inactive = _make_feed(db_session, url="https://example.com/inactive", is_active=False)

    response = client.get("/api/feeds/", params={"active_only": False}, headers=auth_headers)

    assert response.status_code == 200
    ids = {f["id"] for f in response.json()}
    assert ids == {active.id, inactive.id}


# ==================== GET /{feed_id} ====================

def test_get_feed_by_id_returns_feed(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    response = client.get(f"/api/feeds/{feed.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == feed.id


def test_get_feed_by_id_404_when_missing(client, auth_headers):
    response = client.get("/api/feeds/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Feed not found"


# ==================== POST / (create_feed) ====================

def test_create_feed_requires_admin(client, auth_headers):
    response = client.post(
        "/api/feeds/", json={"url": "https://example.com/new-feed"}, headers=auth_headers
    )
    assert response.status_code == 403


def test_create_feed_success(client, admin_headers, db_session):
    with _no_op_safe_url():
        response = client.post(
            "/api/feeds/",
            json={"url": "https://example.com/new-feed", "title": "New Feed"},
            headers=admin_headers,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == "https://example.com/new-feed"
    assert body["title"] == "New Feed"


def test_create_feed_rejects_unsafe_url(client, admin_headers, db_session):
    with _reject_unsafe_url():
        response = client.post(
            "/api/feeds/", json={"url": "https://169.254.169.254/feed"}, headers=admin_headers
        )

    assert response.status_code == 400
    assert db_session.query(models.Feed).count() == 0


def test_create_feed_rejects_duplicate_url(client, admin_headers, db_session):
    _make_feed(db_session, url="https://example.com/dup")

    with _no_op_safe_url():
        response = client.post(
            "/api/feeds/", json={"url": "https://example.com/dup"}, headers=admin_headers
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Feed already exists"


# ==================== PUT /{feed_id} ====================

def test_update_feed_requires_admin(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    response = client.put(f"/api/feeds/{feed.id}", json={"title": "New"}, headers=auth_headers)
    assert response.status_code == 403


def test_update_feed_success_without_url_change(client, admin_headers, db_session):
    feed = _make_feed(db_session)

    with _no_op_safe_url() as mock_safe:
        response = client.put(
            f"/api/feeds/{feed.id}", json={"title": "Renamed"}, headers=admin_headers
        )

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    mock_safe.assert_not_called()


def test_update_feed_404_when_missing(client, admin_headers):
    response = client.put("/api/feeds/999999", json={"title": "X"}, headers=admin_headers)
    assert response.status_code == 404


def test_update_feed_rejects_duplicate_url_on_change(client, admin_headers, db_session):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")

    with _no_op_safe_url() as mock_safe:
        response = client.put(
            f"/api/feeds/{feed_a.id}", json={"url": feed_b.url}, headers=admin_headers
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Feed already exists"
    mock_safe.assert_called_once()


# ==================== POST /{feed_id}/refresh ====================

def test_refresh_feed_queues_background_task(client, auth_headers, db_session):
    feed = _make_feed(db_session)

    with patch("app.tasks.background.process_feed_task", new=AsyncMock()) as mock_task:
        response = client.post(f"/api/feeds/{feed.id}/refresh", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "queued", "feed_id": feed.id}
    mock_task.assert_called_once_with(feed.id)


def test_refresh_feed_404_when_missing(client, auth_headers):
    with patch("app.tasks.background.process_feed_task", new=AsyncMock()) as mock_task:
        response = client.post("/api/feeds/999999/refresh", headers=auth_headers)

    assert response.status_code == 404
    mock_task.assert_not_called()


# ==================== GET /{feed_id}/refresh-status ====================

def test_refresh_status_unknown_feed_returns_idle(client, auth_headers):
    response = client.get("/api/feeds/999999/refresh-status", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"status": "idle"}


def test_refresh_status_returns_mocked_job_dict(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    with patch(
        "app.tasks.background.get_job_status",
        return_value={"status": "running", "processed": 3},
    ):
        response = client.get(f"/api/feeds/{feed.id}/refresh-status", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "running", "processed": 3}


# ==================== DELETE /{feed_id} ====================

def test_delete_feed_requires_admin(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    response = client.delete(f"/api/feeds/{feed.id}", headers=auth_headers)
    assert response.status_code == 403


def test_delete_feed_success(client, admin_headers, db_session):
    feed = _make_feed(db_session)

    response = client.delete(f"/api/feeds/{feed.id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {"status": "deleted", "feed_id": feed.id}
    assert db_session.query(models.Feed).filter(models.Feed.id == feed.id).first() is None


def test_delete_feed_404_when_missing(client, admin_headers):
    response = client.delete("/api/feeds/999999", headers=admin_headers)
    assert response.status_code == 404
