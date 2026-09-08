---
paths:
  - "app/**"
  - "tests/**"
---

# Backend Tests (pytest)

## Required for every feature
- **Every new/changed route or `crud` function gets a `pytest` test in `backend/tests/`** — see
  [[api-routes]], [[db]]. A feature isn't done when it merely runs manually; it's done when a test
  fails if the behavior regresses. Name the file after the router it covers (`test_auth.py` →
  `app/api/routes/auth.py`).
- **Cover the happy path AND the 4xx edges** — missing/invalid auth, bad input, not-found — not just
  the success case.

## Fixtures (`tests/conftest.py`)
- **Use the `client` fixture, never `TestClient(app)` directly.** It overrides `get_db` with an
  isolated in-memory SQLite (`db_session`, via `StaticPool` so the same connection persists for the
  test) and is built **without** entering the app's lifespan context (no `with TestClient(app)`) —
  so `init_db()`/`seed_database()`/the APScheduler never run and never touch the real
  `news_summary.db`.
- **Use `test_user`/`auth_headers` for protected routes** — build a real user row via `crud.create_user`
  and a real JWT via `create_access_token`, don't mock `get_current_user`.
- **A new cross-cutting fixture goes in `conftest.py`**, not duplicated per test file.

## Running
- `cd backend && pytest -q` (uses `pytest.ini`'s `testpaths = tests`).
- `httpx` is pinned `<0.28` in `requirements.txt` — 0.28 dropped `Client(app=...)`, which the
  `TestClient` on this FastAPI/starlette pin needs. Don't bump past 0.28 without checking that first.
