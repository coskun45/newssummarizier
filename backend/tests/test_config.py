"""
Regression (#35): `core/config.py` defaults and the root `.env.example` template drifted apart (token
limits 10x apart, a different daily cost limit, a key no code read). They must agree, since
`.env.example` is what every install's `.env` is generated from.
"""
from pathlib import Path

import pytest

from app.core.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"

# Keys read by docker compose only, not by the backend Settings.
COMPOSE_ONLY = {"POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"}
# Keys whose template value is a deliberate placeholder / local-dev value, not the code default.
DIFFERENT_ON_PURPOSE = {"OPENAI_API_KEY", "DATABASE_URL", "CORS_ORIGINS", "ADMIN_EMAIL", "ADMIN_PASSWORD"}


def _env_example() -> dict:
    values = {}
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split("  #")[0].strip()
    return values


def test_every_env_example_key_is_read_by_the_backend():
    fields = {name.upper() for name in Settings.model_fields}
    unknown = set(_env_example()) - fields - COMPOSE_ONLY
    assert unknown == set(), f"keys in .env.example that no code reads: {sorted(unknown)}"


@pytest.mark.parametrize("key", sorted(set(_env_example()) - COMPOSE_ONLY - DIFFERENT_ON_PURPOSE))
def test_env_example_matches_the_code_default(key):
    field = Settings.model_fields[key.lower()]
    template = _env_example()[key]
    default = field.default
    if isinstance(default, bool):
        assert template.lower() == str(default).lower()
    elif isinstance(default, (int, float)):
        assert float(template) == float(default)
    else:
        assert template == str(default)
