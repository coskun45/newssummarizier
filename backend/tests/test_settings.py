"""
Tests for app/api/routes/settings.py — the global pipeline settings. Anyone signed in can read
them; only admins can change them (they steer the pipeline for every user).
"""
import asyncio

import pytest

from app.db import crud
from app.services import summary_service
from tests.conftest import _make_topic


def _put(client, headers, **overrides):
    body = {"enabled_topics": "", "enabled_summary_types": "brief", "feed_refresh_interval": 3600}
    body.update(overrides)
    return client.put("/api/settings/", json=body, headers=headers)


def test_get_settings_requires_auth(client):
    response = client.get("/api/settings/")
    assert response.status_code == 401


def test_get_settings_returns_defaults_when_empty(client, auth_headers):
    from app.core.config import settings

    response = client.get("/api/settings/", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "enabled_topics": "",
        "enabled_summary_types": "brief,standard,detailed",
        "feed_refresh_interval": settings.feed_refresh_interval,
    }


def test_refresh_interval_code_default_is_hourly():
    """The scheduler always ran hourly; that stays the default until an admin changes it."""
    from app.core.config import Settings

    assert Settings.model_fields["feed_refresh_interval"].default == 3600


def test_put_settings_persists_and_is_read_back(client, admin_headers, db_session):
    t1, t2 = _make_topic(db_session, "A"), _make_topic(db_session, "B")
    put_response = _put(client, admin_headers, enabled_topics=f"{t1.id},{t2.id}",
                        enabled_summary_types="brief", feed_refresh_interval=600)
    get_response = client.get("/api/settings/", headers=admin_headers)

    assert put_response.status_code == 200
    assert get_response.json() == {
        "enabled_topics": f"{t1.id},{t2.id}",
        "enabled_summary_types": "brief",
        "feed_refresh_interval": 600,
    }


def test_put_settings_requires_admin(client, auth_headers):
    """Regression (#32): any signed-in user could change the global pipeline settings."""
    response = _put(client, auth_headers)
    assert response.status_code == 403


@pytest.mark.parametrize("value", ["", " , ", "summary", "brief,long"])
def test_put_settings_rejects_empty_or_unknown_summary_types(client, admin_headers, db_session, value):
    """Regression (#24): an empty selection was stored as "" and read back as "all three types",
    so turning every type off generated the most expensive setup."""
    response = _put(client, admin_headers, enabled_summary_types=value)

    assert response.status_code == 422
    assert crud.get_setting(db_session, "enabled_summary_types") is None


def test_put_settings_normalizes_summary_types(client, admin_headers):
    response = _put(client, admin_headers, enabled_summary_types=" detailed ,brief,brief")
    assert response.json()["enabled_summary_types"] == "brief,detailed"


@pytest.mark.parametrize("stored, expected", [
    (None, ["brief", "standard", "detailed"]),
    ("detailed,brief", ["brief", "detailed"]),
    ("", ["brief", "standard", "detailed"]),  # legacy row written before validation existed
])
def test_enabled_summary_types_reader(db_session, stored, expected):
    if stored is not None:
        crud.set_setting(db_session, "enabled_summary_types", stored)
    assert summary_service.get_enabled_summary_types(db_session) == expected


@pytest.mark.parametrize("interval", [-1, 0, 60, 7 * 24 * 3600])
def test_put_settings_rejects_out_of_range_refresh_interval(client, admin_headers, interval):
    response = _put(client, admin_headers, feed_refresh_interval=interval)
    assert response.status_code == 422


def test_put_settings_rejects_malformed_topic_ids(client, admin_headers):
    response = _put(client, admin_headers, enabled_topics="1,abc")
    assert response.status_code == 422


def test_put_settings_reschedules_feed_refresh(client, admin_headers, monkeypatch):
    """Regression (#27): the refresh interval was saved but the scheduler ran hourly regardless."""
    from app.tasks import scheduler

    calls = []
    monkeypatch.setattr(scheduler, "reschedule_feed_processing", calls.append)

    response = _put(client, admin_headers, feed_refresh_interval=900)

    assert response.status_code == 200
    assert calls == [900]


def test_saving_other_settings_does_not_reschedule_feed_refresh(client, admin_headers, db_session, monkeypatch):
    """Rescheduling moves the next run to now + interval, so saving e.g. only Kategoriler must not
    postpone the next automatic refresh when the interval itself didn't change."""
    from app.tasks import scheduler

    crud.set_setting(db_session, "feed_refresh_interval", "3600")
    calls = []
    monkeypatch.setattr(scheduler, "reschedule_feed_processing", calls.append)

    response = _put(client, admin_headers, enabled_summary_types="brief,standard", feed_refresh_interval=3600)

    assert response.status_code == 200
    assert calls == []


def test_scheduler_uses_the_stored_refresh_interval(monkeypatch, db_session):
    from sqlalchemy.orm import sessionmaker
    from app.db import database
    from app.tasks import scheduler

    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db_session.get_bind()))
    crud.set_setting(db_session, "feed_refresh_interval", "900")

    async def run():
        scheduler.start_scheduler()
        try:
            first = scheduler._scheduler.get_job(scheduler.JOB_ID).trigger.interval.total_seconds()
            scheduler.reschedule_feed_processing(1800)
            second = scheduler._scheduler.get_job(scheduler.JOB_ID).trigger.interval.total_seconds()
        finally:
            scheduler.stop_scheduler()
        return first, second

    assert asyncio.run(run()) == (900, 1800)
