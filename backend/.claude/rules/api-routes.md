---
paths:
  - "app/api/routes/**"
  - "app/api/deps.py"
  - "app/main.py"
---

# FastAPI Routes

## Router wiring
- **Routers define no prefix internally** — each `APIRouter()` is mounted with its prefix and `tags` in `app/main.py` (`include_router(..., prefix="/api/articles")`). Add a new route module by creating `app/api/routes/<name>.py` exposing `router = APIRouter()` and registering it in `main.py`'s import list and `include_router` block.
- **All routers except `auth` require JWT** — protected routers are mounted with `dependencies=auth_dep` (`[Depends(get_current_user)]`) in `main.py`. A new protected router MUST be added with `dependencies=auth_dep`; only public endpoints (login, health, info) omit it.
- **`summaries` router is mounted at bare `/api`** (not `/api/summaries`) because its paths are article-scoped (`/articles/{id}/summary/...`). Keep summary endpoints under the article path, not a top-level `/summaries`.

## Handlers
- **ALWAYS inject the session with `db: Session = Depends(get_db)`** — never construct a `SessionLocal()` inside a request handler (that pattern is reserved for background/agent code, see [[langgraph-agent]]).
- **ALWAYS go through `crud.*` for DB access** — handlers call functions in `app.db.crud`, not raw `db.query(...)`. The ad-hoc `db.query` in `/articles/counts` is a deliberate aggregation exception; don't spread it.
- **Raise `HTTPException` for client errors** — 404 when a `crud.get_*` returns `None`, 400 for malformed input (e.g. unparseable comma-separated `topic_ids`). Don't return error dicts.
- **Define Pydantic request/response models in the route module** next to the handler, set `response_model=` on the decorator, and use `class Config: from_attributes = True` for ORM-backed responses.
- **Comma-separated list query params** (`topic_ids`, `feed_ids`) are passed as `Optional[str]` and parsed with a `try/int` that raises 400 on failure — follow this for any new multi-value filter.
- **Constrain pagination** with `Query(0, ge=0)` / `Query(50, ge=1, le=100)`; don't accept unbounded `limit`.
