"""
Tests for app/api/routes/settings.py — a plain key-value store, JWT-only
(no admin requirement on writes, unlike topics/prompts/rss).
"""


def test_get_settings_requires_auth(client):
    response = client.get("/api/settings/")
    assert response.status_code == 401


def test_get_settings_returns_defaults_when_empty(client, auth_headers):
    response = client.get("/api/settings/", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "enabled_topics": "",
        "enabled_summary_types": "brief,standard,detailed",
        "feed_refresh_interval": 1800,
    }


def test_put_settings_persists_and_is_read_back(client, auth_headers):
    put_response = client.put(
        "/api/settings/",
        json={
            "enabled_topics": "1,2",
            "enabled_summary_types": "brief",
            "feed_refresh_interval": 600,
        },
        headers=auth_headers,
    )
    get_response = client.get("/api/settings/", headers=auth_headers)

    assert put_response.status_code == 200
    assert get_response.status_code == 200
    assert get_response.json() == {
        "enabled_topics": "1,2",
        "enabled_summary_types": "brief",
        "feed_refresh_interval": 600,
    }


def test_put_settings_does_not_require_admin(client, auth_headers):
    response = client.put(
        "/api/settings/",
        json={"enabled_topics": "", "enabled_summary_types": "brief", "feed_refresh_interval": 300},
        headers=auth_headers,
    )
    assert response.status_code == 200


def test_put_settings_accepts_unvalidated_negative_interval(client, auth_headers):
    response = client.put(
        "/api/settings/",
        json={"enabled_topics": "", "enabled_summary_types": "brief", "feed_refresh_interval": -1},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["feed_refresh_interval"] == -1
