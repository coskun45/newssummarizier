"""scripts/ensure_env.py — sunucudaki tek .env dosyasını hazırlayan script."""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ensure_env.py"
_spec = importlib.util.spec_from_file_location("ensure_env", _SCRIPT)
ensure_env_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ensure_env_mod)

EXAMPLE = """OPENAI_API_KEY=your-openai-api-key-here
POSTGRES_USER=bulten
POSTGRES_PASSWORD=changeme
POSTGRES_DB=bulten
DATABASE_URL=postgresql+psycopg2://bulten:changeme@localhost:5432/bulten
DEBUG=True
MAX_TOKENS_INPUT=40000  # yorum
CORS_ORIGINS=http://localhost:5173
JWT_SECRET_KEY=change-me-in-production-use-32-char-minimum-secret-key
ADMIN_EMAIL=
ADMIN_PASSWORD=
"""


@pytest.fixture
def root(tmp_path):
    (tmp_path / ".env.example").write_text(EXAMPLE, encoding="utf-8")
    (tmp_path / "backend").mkdir()
    return tmp_path


def _values(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key] = value
    return out


def test_fresh_env_gets_generated_secrets_and_initial_values(root):
    done = ensure_env_mod.ensure_env(
        root, {"OPENAI_API_KEY": "sk-test", "ADMIN_EMAIL": "a@b.de", "ADMIN_PASSWORD": "pw"}, "1.2.3.4"
    )
    v = _values(root / ".env")
    assert done["created"] is True
    assert v["OPENAI_API_KEY"] == "sk-test"
    assert v["ADMIN_EMAIL"] == "a@b.de"
    assert v["POSTGRES_PASSWORD"] != "changeme"
    assert v["POSTGRES_PASSWORD"] in v["DATABASE_URL"]
    assert v["JWT_SECRET_KEY"] != ensure_env_mod.DEFAULT_JWT
    assert v["DEBUG"] == "False"
    assert v["CORS_ORIGINS"] == "http://1.2.3.4"
    assert v["MAX_TOKENS_INPUT"] == "40000  # yorum"


def test_second_run_is_idempotent_and_keeps_manual_edits(root):
    ensure_env_mod.ensure_env(root, {"OPENAI_API_KEY": "sk-first"}, "1.2.3.4")
    first = _values(root / ".env")

    env_path = root / ".env"
    env_path.write_text(
        env_path.read_text(encoding="utf-8").replace("MAX_TOKENS_INPUT=40000  # yorum", "MAX_TOKENS_INPUT=1234"),
        encoding="utf-8",
    )
    done = ensure_env_mod.ensure_env(root, {"OPENAI_API_KEY": "sk-second"}, "9.9.9.9")
    second = _values(env_path)

    assert done["created"] is False
    assert second["MAX_TOKENS_INPUT"] == "1234"
    assert second["OPENAI_API_KEY"] == "sk-first"
    assert second["POSTGRES_PASSWORD"] == first["POSTGRES_PASSWORD"]
    assert second["JWT_SECRET_KEY"] == first["JWT_SECRET_KEY"]
    assert second["CORS_ORIGINS"] == "http://1.2.3.4"


def test_legacy_backend_env_is_merged_without_container_only_keys(root):
    (root / ".env").write_text("POSTGRES_USER=bulten\nPOSTGRES_PASSWORD=serverpw\nPOSTGRES_DB=bulten\n", encoding="utf-8")
    (root / "backend" / ".env").write_text(
        "OPENAI_API_KEY=sk-legacy\nDATABASE_URL=sqlite:///./x.db\nMAX_TOKENS_INPUT=777\nDEBUG=True\n",
        encoding="utf-8",
    )
    (root / ".jwt_secret").write_text("jwt-from-file\n", encoding="utf-8")

    done = ensure_env_mod.ensure_env(root, {}, None)
    v = _values(root / ".env")

    assert done["migrated_legacy"] is True
    assert not (root / "backend" / ".env").exists()
    assert (root / "backend" / ".env.migrated").exists()
    assert v["OPENAI_API_KEY"] == "sk-legacy"
    assert v["MAX_TOKENS_INPUT"] == "777"
    assert v["POSTGRES_PASSWORD"] == "serverpw"
    assert v["JWT_SECRET_KEY"] == "jwt-from-file"
    assert v["DEBUG"] == "False"
    assert "sqlite" not in v["DATABASE_URL"]


def test_legacy_does_not_override_existing_root_values_and_localhost_cors_gets_server_ip(root):
    (root / ".env").write_text(
        "POSTGRES_USER=bulten\nPOSTGRES_PASSWORD=serverpw\nPOSTGRES_DB=bulten\nMAX_TOKENS_INPUT=1234\n",
        encoding="utf-8",
    )
    (root / "backend" / ".env").write_text(
        "MAX_TOKENS_INPUT=777\nCORS_ORIGINS=http://localhost:5173\n", encoding="utf-8"
    )

    ensure_env_mod.ensure_env(root, {}, "5.6.7.8")
    v = _values(root / ".env")

    assert v["MAX_TOKENS_INPUT"] == "1234"
    assert v["CORS_ORIGINS"] == "http://5.6.7.8"
