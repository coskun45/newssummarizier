"""
Tests for app/api/routes/topics.py.
"""
from app.api.routes.topics import generate_random_color
from tests.conftest import _make_feed, _make_article, _make_topic, _make_article_topic


# ==================== GET / (list_topics) ====================

def test_list_topics_requires_auth(client):
    response = client.get("/api/topics/")
    assert response.status_code == 401


def test_list_topics_empty_returns_200(client, auth_headers):
    response = client.get("/api/topics/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_topics_returns_article_and_unread_counts(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Economy")
    read_article = _make_article(db_session, feed.id, url="https://example.com/t1", is_read=True)
    unread_article = _make_article(db_session, feed.id, url="https://example.com/t2", is_read=False)
    _make_article_topic(db_session, read_article.id, topic.id)
    _make_article_topic(db_session, unread_article.id, topic.id)

    response = client.get("/api/topics/", headers=auth_headers)

    assert response.status_code == 200
    body = next(t for t in response.json() if t["id"] == topic.id)
    assert body["article_count"] == 2
    assert body["unread_count"] == 1


def test_list_topics_filtered_by_feed_id_drops_topics_without_matching_articles(
    client, auth_headers, db_session
):
    feed_a = _make_feed(db_session, url="https://example.com/feed-a")
    feed_b = _make_feed(db_session, url="https://example.com/feed-b")
    topic = _make_topic(db_session, name="Sports")
    article_in_b = _make_article(db_session, feed_b.id, url="https://example.com/t3")
    _make_article_topic(db_session, article_in_b.id, topic.id)

    response = client.get("/api/topics/", params={"feed_id": feed_a.id}, headers=auth_headers)

    assert response.status_code == 200
    ids = {t["id"] for t in response.json()}
    assert topic.id not in ids


# ==================== POST / (create_topic) ====================

def test_create_topic_requires_admin(client, auth_headers):
    response = client.post("/api/topics/", json={"name": "New Topic"}, headers=auth_headers)
    assert response.status_code == 403


def test_create_topic_success_with_explicit_color(client, admin_headers):
    response = client.post(
        "/api/topics/",
        json={"name": "New Topic", "color": "#123456"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "New Topic"
    assert body["color"] == "#123456"
    assert body["article_count"] == 0


def test_create_topic_generates_color_when_omitted(client, admin_headers):
    response = client.post("/api/topics/", json={"name": "No Color"}, headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["color"] in [
        "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
        "#06b6d4", "#f97316", "#6366f1", "#14b8a6", "#84cc16",
    ]


def test_create_topic_rejects_duplicate_name(client, admin_headers, db_session):
    _make_topic(db_session, name="Existing")

    response = client.post("/api/topics/", json={"name": "Existing"}, headers=admin_headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "Topic with this name already exists"


def test_generate_random_color_returns_one_of_fixed_palette():
    color = generate_random_color()
    assert color in [
        "#3b82f6", "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
        "#06b6d4", "#f97316", "#6366f1", "#14b8a6", "#84cc16",
    ]


# ==================== GET /{topic_id} ====================

def test_get_topic_by_id_returns_live_article_count(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, name="Health")
    a1 = _make_article(db_session, feed.id, url="https://example.com/h1")
    a2 = _make_article(db_session, feed.id, url="https://example.com/h2")
    _make_article_topic(db_session, a1.id, topic.id)
    _make_article_topic(db_session, a2.id, topic.id)

    response = client.get(f"/api/topics/{topic.id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["article_count"] == 2


def test_get_topic_by_id_404_when_missing(client, auth_headers):
    response = client.get("/api/topics/999999", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Topic not found"


# ==================== PUT /{topic_id} ====================

def test_update_topic_requires_admin(client, auth_headers, db_session):
    topic = _make_topic(db_session, name="Old Name")
    response = client.put(
        f"/api/topics/{topic.id}", json={"name": "New Name"}, headers=auth_headers
    )
    assert response.status_code == 403


def test_update_topic_renames_successfully(client, admin_headers, db_session):
    topic = _make_topic(db_session, name="Old Name")

    response = client.put(
        f"/api/topics/{topic.id}", json={"name": "New Name"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "New Name"


def test_update_topic_self_rename_to_same_name_is_allowed(client, admin_headers, db_session):
    topic = _make_topic(db_session, name="Same Name")

    response = client.put(
        f"/api/topics/{topic.id}", json={"name": "Same Name"}, headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Same Name"


def test_update_topic_404_when_missing(client, admin_headers):
    response = client.put("/api/topics/999999", json={"name": "X"}, headers=admin_headers)
    assert response.status_code == 404


def test_update_topic_rejects_rename_to_taken_name(client, admin_headers, db_session):
    topic_a = _make_topic(db_session, name="Topic A")
    topic_b = _make_topic(db_session, name="Topic B")

    response = client.put(
        f"/api/topics/{topic_a.id}", json={"name": "Topic B"}, headers=admin_headers
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Topic with this name already exists"


# ==================== DELETE /{topic_id} ====================

def test_delete_topic_requires_admin(client, auth_headers, db_session):
    topic = _make_topic(db_session)
    response = client.delete(f"/api/topics/{topic.id}", headers=auth_headers)
    assert response.status_code == 403


def test_delete_topic_success(client, admin_headers, db_session):
    topic = _make_topic(db_session, name="To Delete")

    response = client.delete(f"/api/topics/{topic.id}", headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "success",
        "message": "Topic 'To Delete' deleted successfully",
    }


def test_delete_topic_404_when_missing(client, admin_headers):
    response = client.delete("/api/topics/999999", headers=admin_headers)
    assert response.status_code == 404
