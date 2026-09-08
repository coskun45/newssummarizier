"""
Example/reference tests for the auth flow — mirror this shape for new routes:
one fixture-driven `client`, real DB rows via `crud`, and both the happy path
and the 401/404 edges.
"""


def test_health_check(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_protected_route_without_token_is_rejected(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_login_with_wrong_password_is_rejected(client, test_user):
    response = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_login_success_returns_token_and_me_works(client, test_user):
    login_response = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "testpass123"},
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]

    me_response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == test_user.email


def test_create_user_requires_admin_role(client, auth_headers):
    response = client.post(
        "/api/auth/users",
        json={"email": "new@example.com", "password": "irrelevant123"},
        headers=auth_headers,
    )
    assert response.status_code == 403
