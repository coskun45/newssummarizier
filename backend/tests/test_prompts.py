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
