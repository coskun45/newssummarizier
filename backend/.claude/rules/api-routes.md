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
- **Links sent by mail (confirm / unsubscribe) live on a separate `public_router` mounted WITHOUT `auth_dep` under a `/public` prefix** (`newsletter.public_router` → `/api/newsletter/public`). The secret token is the authorization: generate it with `secrets.token_urlsafe(32)`, bound the `token` query param's length, and never return tokens in any API response model.
- **On those public links, GET only renders a page with a button; the state change is a POST** — mail scanners (Outlook Safe Links etc.) open every GET link in a mail on their own and would otherwise confirm/unsubscribe for the recipient. The POST URL doubles as the RFC 8058 `List-Unsubscribe-Post` one-click target, so don't require a body.
- **`summaries` router is mounted at bare `/api`** (not `/api/summaries`) because its paths are article-scoped (`/articles/{id}/summary/...`). Keep summary endpoints under the article path, not a top-level `/summaries`.

## Handlers
- **ALWAYS inject the session with `db: Session = Depends(get_db)`** — never construct a `SessionLocal()` inside a request handler (that pattern is reserved for background/agent code, see [[langgraph-agent]]).
- **ALWAYS go through `crud.*` for DB access** — handlers call functions in `app.db.crud`, not raw `db.query(...)` (aggregations too: `/articles/counts` uses `crud.get_article_counts`).
- **Global, destructive or OpenAI-cost-incurring writes are admin-only** — add `current_user: models.User = Depends(require_admin)`: `PUT /settings`, bulk deletes, `/articles/reprocess`, `/playground/run`, deleting generated bulletins, feed/category management. `tests/test_permissions.py` lists them; add a new one there, and hide its button for non-admins in the frontend (`currentUser.role`).
- **Raise `HTTPException` for client errors** — 404 when a `crud.get_*` returns `None`, 400 for malformed input (e.g. unparseable comma-separated `topic_ids`). Don't return error dicts.
- **Define Pydantic request/response models in the route module** next to the handler, set `response_model=` on the decorator, and use `class Config: from_attributes = True` for ORM-backed responses.
- **Comma-separated list query params** (`topic_ids`, `feed_ids`) are passed as `Optional[str]` and parsed with a `try/int` that raises 400 on failure — follow this for any new multi-value filter.
- **Constrain pagination** with `Query(0, ge=0)` / `Query(50, ge=1, le=100)`; don't accept unbounded `limit`.
