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
    body = response.json()
    assert {k: body[k] for k in ("enabled_topics", "enabled_summary_types", "feed_refresh_interval")} == {
        "enabled_topics": "",
        "enabled_summary_types": "brief,standard,detailed",
        "feed_refresh_interval": settings.feed_refresh_interval,
    }
    # Nothing chosen in Ayarlar yet: no choice, the env models are reported as the defaults.
    assert body["classification_model"] is None
    assert body["summary_model"] is None
    assert body["default_models"] == {
        "classification": settings.default_model,
        "summary": settings.default_model,
        "detailed_summary": settings.detailed_model,
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
    body = get_response.json()
    assert {k: body[k] for k in ("enabled_topics", "enabled_summary_types", "feed_refresh_interval")} == {
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


# ---------------------------------------------------------------------------
# Partial updates: each Ayarlar tab saves only its own fields
# ---------------------------------------------------------------------------

def test_put_settings_only_changes_the_fields_sent(client, admin_headers, db_session):
    """Review: one shared save sent every tab's local state, so saving Kategoriler also put an
    unsaved (possibly expensive) model choice live."""
    _put(client, admin_headers, enabled_topics="", enabled_summary_types="brief,detailed",
         feed_refresh_interval=900, classification_model="gpt-4o-mini", summary_model="gpt-4o")

    response = client.put("/api/settings/", json={"enabled_summary_types": "standard"}, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["enabled_summary_types"] == "standard"
    assert body["feed_refresh_interval"] == 900
    assert body["classification_model"] == "gpt-4o-mini"
    assert body["summary_model"] == "gpt-4o"


def test_put_settings_without_models_does_not_freeze_the_env_fallbacks(client, admin_headers, db_session):
    """Saving another tab must not store the env models as an explicit choice (later .env edits
    would then silently do nothing)."""
    _put(client, admin_headers)

    assert crud.get_setting(db_session, "classification_model") is None
    assert crud.get_setting(db_session, "summary_model") is None


def test_settings_save_works_when_the_env_model_is_not_selectable(client, admin_headers, monkeypatch):
    """Review: with DEFAULT_MODEL=gpt-3.5-turbo (not offered in Ayarlar) GET reported it as the
    current model, the UI sent it back and every save of every tab failed with 422."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "default_model", "gpt-3.5-turbo")
    body = client.get("/api/settings/", headers=admin_headers).json()
    assert body["classification_model"] is None
    assert body["default_models"]["classification"] == "gpt-3.5-turbo"

    response = client.put("/api/settings/", json={"enabled_summary_types": "brief"}, headers=admin_headers)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Classification / summary model selection
# ---------------------------------------------------------------------------

def test_model_code_default_is_gpt_6_luna():
    from app.core.config import Settings

    assert Settings.model_fields["default_model"].default == "gpt-6-luna"
    assert Settings.model_fields["detailed_model"].default == "gpt-6-luna"


def test_get_settings_lists_selectable_models_with_prices(client, auth_headers):
    response = client.get("/api/settings/", headers=auth_headers)

    options = {m["id"]: m for m in response.json()["available_models"]}
    assert list(options) == list(summary_service.SELECTABLE_MODELS)
    assert options["gpt-6-luna"] == {"id": "gpt-6-luna", "input_per_1m": 0.10, "output_per_1m": 0.50}
    assert options["gpt-4o"] == {"id": "gpt-4o", "input_per_1m": 2.50, "output_per_1m": 10.00}


def test_put_settings_saves_the_models(client, admin_headers, db_session):
    response = client.put("/api/settings/", json={"classification_model": "gpt-4o-mini", "summary_model": "gpt-6.1-sol"},
                          headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["classification_model"] == "gpt-4o-mini"
    assert response.json()["summary_model"] == "gpt-6.1-sol"
    assert summary_service.get_classification_model(db_session) == "gpt-4o-mini"
    assert all(summary_service.get_summary_model(db_session, t) == "gpt-6.1-sol" for t in summary_service.SUMMARY_TYPES)


@pytest.mark.parametrize("field", ["classification_model", "summary_model"])
def test_put_settings_rejects_unknown_model(client, admin_headers, field):
    response = client.put("/api/settings/", json={field: "gpt-made-up"}, headers=admin_headers)
    assert response.status_code == 422


def test_put_models_requires_admin(client, auth_headers):
    response = client.put("/api/settings/", json={"summary_model": "gpt-4o"}, headers=auth_headers)
    assert response.status_code == 403


def test_unchosen_summary_model_keeps_each_types_old_env_model(db_session, monkeypatch):
    """Review: an unset summary model fell back to DETAILED_MODEL for every type, so an install
    with DEFAULT_MODEL=gpt-4o-mini / DETAILED_MODEL=gpt-4o silently moved brief and standard
    summaries to gpt-4o (~17x the cost) on deploy."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "default_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "detailed_model", "gpt-4o")

    assert summary_service.get_summary_model(db_session, "brief") == "gpt-4o-mini"
    assert summary_service.get_summary_model(db_session, "standard") == "gpt-4o-mini"
    assert summary_service.get_summary_model(db_session, "detailed") == "gpt-4o"
    assert summary_service.get_classification_model(db_session) == "gpt-4o-mini"


def test_stored_model_no_longer_offered_falls_back_to_env(db_session):
    """A model removed from the catalog must not break the pipeline."""
    from app.core.config import settings

    crud.set_setting(db_session, "classification_model", "gpt-3.5-turbo")
    crud.set_setting(db_session, "summary_model", "")

    assert summary_service.saved_model(db_session, "classification_model") is None
    assert summary_service.get_classification_model(db_session) == settings.default_model
    assert summary_service.get_summary_model(db_session, "detailed") == settings.detailed_model


def test_put_empty_model_clears_the_choice_back_to_the_env_fallbacks(client, admin_headers, db_session):
    """Review: once a model was saved there was no way back to DEFAULT_MODEL / DETAILED_MODEL."""
    from app.core.config import settings

    client.put("/api/settings/", json={"classification_model": "gpt-4o", "summary_model": "gpt-4o"}, headers=admin_headers)
    response = client.put("/api/settings/", json={"classification_model": "", "summary_model": ""}, headers=admin_headers)

    assert response.status_code == 200
    assert response.json()["classification_model"] is None and response.json()["summary_model"] is None
    assert summary_service.get_classification_model(db_session) == settings.default_model
    assert summary_service.get_summary_model(db_session, "detailed") == settings.detailed_model
