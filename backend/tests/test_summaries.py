"""
Tests for app/api/routes/summaries.py (article summaries + cost stats).
"""
from app.core.config import settings
from tests.conftest import _make_feed, _make_article, _make_summary


# ==================== GET /articles/{article_id}/summaries ====================

def test_get_article_summaries_requires_auth(client):
    response = client.get("/api/articles/1/summaries")
    assert response.status_code == 401


def test_get_article_summaries_404_when_article_missing(client, auth_headers):
    response = client.get("/api/articles/999999/summaries", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


def test_get_article_summaries_returns_all_types(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, summary_type="brief")
    _make_summary(db_session, article.id, summary_type="standard")

    response = client.get(f"/api/articles/{article.id}/summaries", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_article_summaries_filters_by_summary_type(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, summary_type="brief")
    _make_summary(db_session, article.id, summary_type="standard")

    response = client.get(
        f"/api/articles/{article.id}/summaries",
        params={"summary_type": "brief"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["summary_type"] == "brief"


# ==================== GET /articles/{article_id}/summary/{summary_type} ====================

def test_get_article_summary_by_type_invalid_type_returns_400(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)

    response = client.get(
        f"/api/articles/{article.id}/summary/urgent", headers=auth_headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid summary type"


def test_get_article_summary_by_type_404_when_article_missing(client, auth_headers):
    response = client.get("/api/articles/999999/summary/brief", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"


def test_get_article_summary_by_type_404_when_none_of_that_type(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, summary_type="brief")

    response = client.get(f"/api/articles/{article.id}/summary/detailed", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "No detailed summary found for this article"


def test_get_article_summary_by_type_returns_most_recent(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, summary_type="brief", summary_text="first")
    second = _make_summary(db_session, article.id, summary_type="brief", summary_text="second")

    response = client.get(f"/api/articles/{article.id}/summary/brief", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == second.id


# ==================== GET /stats/costs ====================

def test_get_cost_stats_requires_auth(client):
    response = client.get("/api/stats/costs")
    assert response.status_code == 401


def test_get_cost_stats_defaults_when_no_summaries(client, auth_headers):
    response = client.get("/api/stats/costs", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["daily_cost"] == 0.0
    assert body["monthly_cost"] == 0.0
    assert body["daily_limit"] == settings.daily_cost_limit
    assert body["monthly_limit"] == settings.monthly_cost_limit


def test_get_cost_stats_reflects_recent_summary_cost(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, cost=1.5)

    response = client.get("/api/stats/costs", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["daily_cost"] >= 1.5
    assert body["monthly_cost"] >= 1.5
