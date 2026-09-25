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
    # Shown verbatim on the (Turkish) login page
    assert response.json()["detail"] == "E-posta veya şifre hatalı"


def test_login_to_inactive_account_is_rejected_in_turkish(client, test_user, db_session):
    test_user.is_active = False
    db_session.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": test_user.email, "password": "testpass123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Hesap devre dışı"


def test_create_user_with_existing_email_is_rejected_in_turkish(client, admin_headers, test_user):
    response = client.post(
        "/api/auth/users",
        json={"email": test_user.email, "password": "whatever123", "role": "user"},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Bu e-posta adresi zaten kayıtlı"


def test_admin_cannot_delete_own_account_message_is_turkish(client, admin_headers, admin_user):
    response = client.delete(f"/api/auth/users/{admin_user.id}", headers=admin_headers)
    assert response.status_code == 400
    assert response.json()["detail"] == "Kendi hesabınızı silemezsiniz"


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


# ---------------------------------------------------------------------------
# POST /api/auth/dev-login — local-dev-only auto login (DEV_AUTO_LOGIN + DEBUG)
# ---------------------------------------------------------------------------

def _dev_mode(monkeypatch, *, dev_auto_login=True, debug=True, admin_email=None):
    from app.core.config import settings
    monkeypatch.setattr(settings, "dev_auto_login", dev_auto_login)
    monkeypatch.setattr(settings, "debug", debug)
    monkeypatch.setattr(settings, "admin_email", admin_email)


def test_dev_login_returns_admin_token_that_works(client, monkeypatch, test_user, admin_user):
    _dev_mode(monkeypatch)
    response = client.post("/api/auth/dev-login")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == admin_user.email

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_dev_login_prefers_configured_admin_email(client, monkeypatch, admin_user, db_session):
    from app.db import crud
    from app.core.security import hash_password
    crud.create_user(db=db_session, email="second-admin@example.com",
                     hashed_password=hash_password("x" * 12), role="admin")
    _dev_mode(monkeypatch, admin_email="second-admin@example.com")
    response = client.post("/api/auth/dev-login")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "second-admin@example.com"


def test_dev_login_disabled_by_default(client, monkeypatch, admin_user):
    _dev_mode(monkeypatch, dev_auto_login=False)
    assert client.post("/api/auth/dev-login").status_code == 404


def test_dev_login_refused_outside_debug(client, monkeypatch, admin_user):
    _dev_mode(monkeypatch, debug=False)
    assert client.post("/api/auth/dev-login").status_code == 404


def test_dev_login_without_admin_user_is_404(client, monkeypatch, test_user):
    _dev_mode(monkeypatch)
    assert client.post("/api/auth/dev-login").status_code == 404


# ==================== #33: password policy, e-mail case ====================

def test_create_user_rejects_a_short_password(client, admin_headers):
    response = client.post("/api/auth/users", json={"email": "new@example.com", "password": "kisa"},
                           headers=admin_headers)
    assert response.status_code == 422


def test_create_user_email_is_case_insensitive_and_stored_lowercase(client, admin_headers, test_user):
    """Regression: `Tester@Example.com` could be registered next to `tester@example.com`."""
    duplicate = client.post("/api/auth/users", json={"email": "Tester@Example.COM", "password": "yeterince-uzun"},
                            headers=admin_headers)
    assert duplicate.status_code == 400

    created = client.post("/api/auth/users", json={"email": "  New.User@Example.com ", "password": "yeterince-uzun"},
                          headers=admin_headers)
    assert created.status_code == 201
    assert created.json()["email"] == "new.user@example.com"


def test_login_ignores_email_case(client, test_user):
    response = client.post("/api/auth/login", json={"email": "TESTER@example.com", "password": "testpass123"})
    assert response.status_code == 200


def test_login_finds_a_legacy_mixed_case_account(client, db_session):
    from app.core.security import hash_password
    from app.db import models

    db_session.add(models.User(email="Legacy@Example.com", hashed_password=hash_password("testpass123"), role="user"))
    db_session.commit()

    response = client.post("/api/auth/login", json={"email": "legacy@example.com", "password": "testpass123"})
    assert response.status_code == 200
