"""
Tests for app/api/routes/prompts.py (system prompt CRUD, POST is an upsert).
"""


# ==================== GET / ====================

def test_list_prompts_requires_auth(client):
    response = client.get("/api/prompts/")
    assert response.status_code == 401


def test_list_prompts_empty_returns_200(client, auth_headers):
    response = client.get("/api/prompts/", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


# ==================== GET /{prompt_type} ====================

def test_get_prompt_by_type_404_when_missing(client, auth_headers):
    response = client.get("/api/prompts/classification", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "System prompt 'classification' not found"


def test_get_prompt_by_type_returns_created_prompt(client, admin_headers, auth_headers):
    client.post(
        "/api/prompts/",
        json={"prompt_type": "classification", "prompt_text": "Classify this article."},
        headers=admin_headers,
    )

    response = client.get("/api/prompts/classification", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_type"] == "classification"
    assert body["prompt_text"] == "Classify this article."
    assert body["is_active"] is True


# ==================== POST / (create/upsert) ====================

def test_create_prompt_requires_admin(client, auth_headers):
    response = client.post(
        "/api/prompts/",
        json={"prompt_type": "classification", "prompt_text": "x"},
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_create_prompt_success(client, admin_headers):
    response = client.post(
        "/api/prompts/",
        json={"prompt_type": "summarization", "prompt_text": "Summarize this."},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] is not None
    assert body["created_at"] is not None
    assert body["updated_at"] is not None
    assert body["is_active"] is True


def test_create_prompt_upserts_existing_type(client, admin_headers):
    first = client.post(
        "/api/prompts/",
        json={"prompt_type": "classification", "prompt_text": "First version"},
        headers=admin_headers,
    )
    second = client.post(
        "/api/prompts/",
        json={"prompt_type": "classification", "prompt_text": "Second version"},
        headers=admin_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["prompt_text"] == "Second version"

    all_prompts = client.get("/api/prompts/", headers=admin_headers).json()
    matching = [p for p in all_prompts if p["prompt_type"] == "classification"]
    assert len(matching) == 1


# ==================== PUT /{prompt_type} ====================

def test_update_prompt_requires_admin(client, auth_headers):
    response = client.put(
        "/api/prompts/classification", json={"prompt_text": "x"}, headers=auth_headers
    )
    assert response.status_code == 403


def test_update_prompt_success_partial(client, admin_headers):
    client.post(
        "/api/prompts/",
        json={"prompt_type": "classification", "prompt_text": "Original", "is_active": True},
        headers=admin_headers,
    )

    response = client.put(
        "/api/prompts/classification",
        json={"prompt_text": "Updated"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_text"] == "Updated"
    assert body["is_active"] is True


def test_update_prompt_404_when_type_does_not_exist(client, admin_headers):
    response = client.put(
        "/api/prompts/never-created", json={"prompt_text": "x"}, headers=admin_headers
    )
    assert response.status_code == 404


# ==================== GET /{prompt_type}/locked ====================

def test_locked_prompt_requires_auth(client):
    assert client.get("/api/prompts/classification/locked").status_code == 401


def test_locked_classification_prompt_renders_live_topics_and_format(client, auth_headers, db_session):
    from tests.conftest import _make_topic
    _make_topic(db_session, "NATO", description="Bündnis")

    response = client.get("/api/prompts/classification/locked", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["prompt_type"] == "classification"
    assert "- NATO: Bündnis" in body["locked_text"]
    assert '"importance"' in body["locked_text"] and "JSON" in body["locked_text"]


def test_locked_summarization_prompt_lists_summary_type_instructions(client, auth_headers):
    from app.services import summary_service

    response = client.get("/api/prompts/summarization/locked", headers=auth_headers)

    assert response.status_code == 200
    locked = response.json()["locked_text"]
    for summary_type, instructions in summary_service.DEFAULT_SUMMARY_INSTRUCTIONS.items():
        assert f"{summary_type}: {instructions}" in locked
    assert summary_service.SUMMARY_LANGUAGE_INSTRUCTION in locked


def test_locked_summarization_text_matches_what_the_model_receives():
    """The read-only text must not drift from the real user message the summary call sends."""
    from app.services import summary_service

    for summary_type, instructions in summary_service.DEFAULT_SUMMARY_INSTRUCTIONS.items():
        user_prompt = summary_service._build_summary_user_prompt("T", "C", instructions)
        assert f"Instructions: {instructions}" in user_prompt
        assert f"{summary_type}: {instructions}" in summary_service.build_summarization_locked_text()
    assert user_prompt.endswith(summary_service.SUMMARY_LANGUAGE_INSTRUCTION)


def test_locked_prompt_is_empty_for_types_without_locked_part(client, auth_headers):
    response = client.get("/api/prompts/something-else/locked", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["locked_text"] == ""


def test_locked_text_cannot_be_changed_through_prompt_endpoints(client, admin_headers, auth_headers, db_session):
    """Extra `locked_text` in a save request is ignored; the locked part always comes from code."""
    from tests.conftest import _make_topic
    _make_topic(db_session, "NATO", description="Bündnis")
    client.post("/api/prompts/", json={
        "prompt_type": "classification", "prompt_text": "Kriter", "locked_text": "HACKED",
    }, headers=admin_headers)
    client.put("/api/prompts/classification", json={"prompt_text": "Kriter 2", "locked_text": "HACKED"},
               headers=admin_headers)

    stored = client.get("/api/prompts/classification", headers=auth_headers).json()
    locked = client.get("/api/prompts/classification/locked", headers=auth_headers).json()

    assert stored["prompt_text"] == "Kriter 2" and "locked_text" not in stored
    assert "HACKED" not in locked["locked_text"] and "- NATO: Bündnis" in locked["locked_text"]


# ==================== summarization locked part follows the enabled summary types ====================

def _summary_locked(client, headers):
    return client.get("/api/prompts/summarization/locked", headers=headers).json()["locked_text"]


def test_locked_summarization_lists_only_enabled_summary_types(client, auth_headers, db_session):
    from app.db import crud

    crud.set_setting(db_session, "enabled_summary_types", "brief,detailed")

    locked = _summary_locked(client, auth_headers)

    assert "brief: " in locked and "detailed: " in locked
    assert "standard: " not in locked


def test_locked_summarization_follows_setting_changes(client, auth_headers, db_session):
    from app.db import crud

    assert all(f"{t}: " in _summary_locked(client, auth_headers) for t in ("brief", "standard", "detailed"))

    crud.set_setting(db_session, "enabled_summary_types", "standard")

    locked = _summary_locked(client, auth_headers)
    assert "standard: " in locked
    assert "brief: " not in locked and "detailed: " not in locked


def test_locked_summarization_without_valid_types_shows_the_default_types(client, auth_headers, db_session):
    """A stored value with no known type falls back to all types — what the pipeline generates."""
    from app.db import crud
    from app.services import summary_service

    crud.set_setting(db_session, "enabled_summary_types", "bogus")

    locked = _summary_locked(client, auth_headers)

    assert all(f"{t}:" in locked for t in summary_service.SUMMARY_TYPES)
    # The language line is fixed and still shown.
    assert summary_service.SUMMARY_LANGUAGE_INSTRUCTION in locked


def test_prompt_without_timestamps_does_not_500(client, auth_headers, db_session):
    """Regression (#33): created_at/updated_at are nullable but the response required a string."""
    from app.db import models

    prompt = models.SystemPrompt(prompt_type="classification", prompt_text="metin", is_active=True)
    db_session.add(prompt)
    db_session.commit()
    prompt.created_at = None
    prompt.updated_at = None
    db_session.commit()

    response = client.get("/api/prompts/classification", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["created_at"] is None
