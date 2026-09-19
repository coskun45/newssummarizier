"""GET /api/info — herkese açık; UI'daki sürüm etiketi (profil simgesinin altı) bunu okur."""
from app.core.config import settings


def test_info_is_public_and_returns_configured_version(client, monkeypatch):
    # APP_VERSION deploy'da CI'dan (docker-compose → env) gelir; endpoint onu aynen döndürmeli.
    monkeypatch.setattr(settings, "app_version", "2.4.0")

    response = client.get("/api/info")  # Authorization başlığı yok: JWT gerekmez

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2.4.0"
    assert body["status"] == "running"
