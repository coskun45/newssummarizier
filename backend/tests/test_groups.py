"""
Tests for app/api/routes/groups.py and the group_id field on feeds/topics.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.db import crud, models
from tests.conftest import _make_feed, _make_topic


def _make_group(db_session, kind="feed", name="Avrupa", display_order=0):
    return crud.create_group(db_session, kind=kind, name=name, display_order=display_order)


# ==================== GET / (list_groups) ====================

def test_list_groups_requires_auth(client):
    assert client.get("/api/groups/", params={"kind": "feed"}).status_code == 401


def test_list_groups_requires_valid_kind(client, auth_headers):
    assert client.get("/api/groups/", headers=auth_headers).status_code == 422
    assert client.get("/api/groups/", params={"kind": "x"}, headers=auth_headers).status_code == 422


def test_list_groups_filters_by_kind_in_display_order(client, auth_headers, db_session):
    _make_group(db_session, "feed", "Zeta", display_order=0)
    _make_group(db_session, "feed", "Alfa", display_order=1)
    _make_group(db_session, "topic", "Ekonomi")

    response = client.get("/api/groups/", params={"kind": "feed"}, headers=auth_headers)

    assert response.status_code == 200
    assert [g["name"] for g in response.json()] == ["Zeta", "Alfa"]
    assert {g["kind"] for g in response.json()} == {"feed"}


# ==================== POST / (create_group) ====================

def test_create_group_requires_admin(client, auth_headers):
    response = client.post("/api/groups/", json={"kind": "feed", "name": "Avrupa"}, headers=auth_headers)
    assert response.status_code == 403


def test_create_group_success_trims_name(client, admin_headers):
    response = client.post("/api/groups/", json={"kind": "topic", "name": "  Ekonomi "}, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Ekonomi"
    assert body["kind"] == "topic"


@pytest.mark.parametrize("name", ["", "   ", "Diğer", "diğer", "DİĞER", "x" * 101])
def test_create_group_rejects_blank_or_reserved_name(client, admin_headers, name):
    response = client.post("/api/groups/", json={"kind": "feed", "name": name}, headers=admin_headers)
    assert response.status_code == 422


def test_create_group_rejects_duplicate_name_within_kind(client, admin_headers, db_session):
    _make_group(db_session, "feed", "Avrupa")

    dup = client.post("/api/groups/", json={"kind": "feed", "name": "avrupa"}, headers=admin_headers)
    other_kind = client.post("/api/groups/", json={"kind": "topic", "name": "Avrupa"}, headers=admin_headers)

    assert dup.status_code == 400
    assert other_kind.status_code == 200


@pytest.mark.parametrize("existing, new", [("İstanbul", "istanbul"), ("Çin", "ÇİN"), ("Irak", "ırak")])
def test_create_group_duplicate_check_handles_turkish_letters(client, admin_headers, db_session, existing, new):
    """Python's lower() and SQL lower() disagree on İ/ı and non-ASCII letters; a missed duplicate
    used to hit the unique constraint and return 500."""
    _make_group(db_session, "feed", existing)

    response = client.post("/api/groups/", json={"kind": "feed", "name": new}, headers=admin_headers)

    assert response.status_code == 400


def test_create_group_unique_constraint_race_returns_400(client, admin_headers, db_session):
    """If the name check misses (concurrent insert), the unique constraint is turned into a 400."""
    _make_group(db_session, "feed", "Avrupa")

    with patch("app.db.crud.get_group_by_name", return_value=None):
        response = client.post("/api/groups/", json={"kind": "feed", "name": "Avrupa"}, headers=admin_headers)

    assert response.status_code == 400
    assert db_session.query(models.ItemGroup).count() == 1


def test_update_group_rename_to_turkish_case_variant_of_other_returns_400(client, admin_headers, db_session):
    _make_group(db_session, "topic", "İklim")
    group = _make_group(db_session, "topic", "Enerji")

    response = client.put(f"/api/groups/{group.id}", json={"name": "iklim"}, headers=admin_headers)

    assert response.status_code == 400


# ==================== PUT /{id} (update_group) ====================

def test_update_group_renames(client, admin_headers, db_session):
    group = _make_group(db_session, "feed", "Avrupa")

    response = client.put(f"/api/groups/{group.id}", json={"name": "Asya"}, headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["name"] == "Asya"


def test_update_group_rejects_taken_name(client, admin_headers, db_session):
    _make_group(db_session, "feed", "Avrupa")
    group = _make_group(db_session, "feed", "Asya")

    response = client.put(f"/api/groups/{group.id}", json={"name": "Avrupa"}, headers=admin_headers)

    assert response.status_code == 400


def test_update_group_not_found(client, admin_headers):
    assert client.put("/api/groups/999", json={"name": "X"}, headers=admin_headers).status_code == 404


def test_update_group_requires_admin(client, auth_headers, db_session):
    group = _make_group(db_session)
    assert client.put(f"/api/groups/{group.id}", json={"name": "X"}, headers=auth_headers).status_code == 403


# ==================== DELETE /{id} (delete_group) ====================

def test_delete_group_moves_members_to_other(client, admin_headers, db_session):
    feed_group = _make_group(db_session, "feed", "Avrupa")
    topic_group = _make_group(db_session, "topic", "Ekonomi")
    feed = _make_feed(db_session)
    topic = _make_topic(db_session)
    feed.group_id = feed_group.id
    topic.group_id = topic_group.id
    db_session.commit()

    assert client.delete(f"/api/groups/{feed_group.id}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/groups/{topic_group.id}", headers=admin_headers).status_code == 200

    db_session.expire_all()
    assert db_session.get(models.Feed, feed.id).group_id is None
    assert db_session.get(models.Topic, topic.id).group_id is None
    assert db_session.query(models.ItemGroup).count() == 0


def test_delete_group_not_found(client, admin_headers):
    assert client.delete("/api/groups/999", headers=admin_headers).status_code == 404


def test_delete_group_requires_admin(client, auth_headers, db_session):
    group = _make_group(db_session)
    assert client.delete(f"/api/groups/{group.id}", headers=auth_headers).status_code == 403


# ==================== group_id on feeds ====================

def test_create_feed_with_group(client, admin_headers, db_session):
    group = _make_group(db_session, "feed", "Avrupa")

    with patch("app.api.routes.rss.test_feed_connection", new=AsyncMock()):
        response = client.post(
            "/api/feeds/",
            json={"url": "https://example.com/grouped", "title": "Grouped", "group_id": group.id},
            headers=admin_headers,
        )

    assert response.status_code == 200
    assert response.json()["group_id"] == group.id


def test_create_feed_rejects_topic_group(client, admin_headers, db_session):
    topic_group = _make_group(db_session, "topic", "Ekonomi")

    response = client.post(
        "/api/feeds/",
        json={"url": "https://example.com/grouped", "title": "Grouped", "group_id": topic_group.id},
        headers=admin_headers,
    )

    assert response.status_code == 400
    assert db_session.query(models.Feed).count() == 0


def test_update_feed_sets_keeps_and_clears_group(client, admin_headers, db_session):
    group = _make_group(db_session, "feed", "Avrupa")
    feed = _make_feed(db_session)

    set_resp = client.put(f"/api/feeds/{feed.id}", json={"group_id": group.id}, headers=admin_headers)
    keep_resp = client.put(f"/api/feeds/{feed.id}", json={"title": "Renamed"}, headers=admin_headers)
    clear_resp = client.put(f"/api/feeds/{feed.id}", json={"group_id": None}, headers=admin_headers)

    assert set_resp.json()["group_id"] == group.id
    assert keep_resp.json()["group_id"] == group.id
    assert clear_resp.json()["group_id"] is None


def test_update_feed_rejects_unknown_group(client, admin_headers, db_session):
    feed = _make_feed(db_session)
    response = client.put(f"/api/feeds/{feed.id}", json={"group_id": 999}, headers=admin_headers)
    assert response.status_code == 400


# ==================== group_id on topics ====================

def test_create_topic_with_group_and_list_returns_it(client, admin_headers, db_session):
    group = _make_group(db_session, "topic", "Ekonomi")

    created = client.post("/api/topics/", json={"name": "Borsa", "group_id": group.id}, headers=admin_headers)
    listed = client.get("/api/topics/", headers=admin_headers)

    assert created.status_code == 200
    assert created.json()["group_id"] == group.id
    assert next(t for t in listed.json() if t["name"] == "Borsa")["group_id"] == group.id


def test_create_topic_rejects_feed_group(client, admin_headers, db_session):
    feed_group = _make_group(db_session, "feed", "Avrupa")
    response = client.post("/api/topics/", json={"name": "Borsa", "group_id": feed_group.id}, headers=admin_headers)
    assert response.status_code == 400


def test_update_topic_sets_keeps_and_clears_group(client, admin_headers, db_session):
    group = _make_group(db_session, "topic", "Ekonomi")
    topic = _make_topic(db_session)

    set_resp = client.put(f"/api/topics/{topic.id}", json={"group_id": group.id}, headers=admin_headers)
    keep_resp = client.put(f"/api/topics/{topic.id}", json={"description": "x"}, headers=admin_headers)
    clear_resp = client.put(f"/api/topics/{topic.id}", json={"group_id": None}, headers=admin_headers)

    assert set_resp.json()["group_id"] == group.id
    assert keep_resp.json()["group_id"] == group.id
    assert clear_resp.json()["group_id"] is None
