"""
Regression (#32): global, destructive or OpenAI-cost-incurring actions are admin-only. A regular
signed-in user gets 403 and nothing happens; admins keep full access (covered per router).
"""
import pytest

from app.db import models
from tests.conftest import _make_article, _make_feed

ADMIN_ONLY = [
    ("put", "/api/settings/", {"enabled_topics": "", "enabled_summary_types": "brief", "feed_refresh_interval": 3600}),
    ("post", "/api/articles/priority/high/delete-all", None),
    ("post", "/api/articles/unimportant/delete-all", None),
    ("post", "/api/articles/reprocess", {"article_ids": [1]}),
    ("post", "/api/playground/run", {"article_id": 1, "stages": ["classification"]}),
    ("delete", "/api/bulletin/generated/1", None),
]


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY)
def test_regular_user_gets_403(client, auth_headers, method, path, body):
    kwargs = {"headers": auth_headers}
    if body is not None:
        kwargs["json"] = body
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403


@pytest.mark.parametrize("method, path, body", ADMIN_ONLY)
def test_anonymous_gets_401(client, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401


def test_regular_user_bulk_delete_deletes_nothing(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, priority="high")

    client.post("/api/articles/priority/high/delete-all", headers=auth_headers)

    assert db_session.query(models.Article).count() == 1


def test_reading_settings_stays_open_to_regular_users(client, auth_headers):
    """Reading stays open: the list below is about writes only."""
    assert client.get("/api/settings/", headers=auth_headers).status_code == 200
