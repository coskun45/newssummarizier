---
name: implement-requirement
description: Implement a new feature or requirement end-to-end across the Bülten stack (FastAPI backend + React frontend). Use when asked to add a capability, endpoint, field, filter, setting, or UI feature that touches one or both layers. Walks the change through the project's layered conventions and finishes with docs + verification.
---

# Implement a Requirement (end-to-end)

Bülten is a two-service app: a Python **FastAPI** backend (`backend/`) and a **React + Vite +
TypeScript** frontend (`frontend/`), talking over `/api`. Most requirements cut across layers in a
fixed order — follow it so the change stays consistent with the existing code and the `.claude/rules/`.

Don't build everything at once. Decide which layers the requirement actually touches, then implement
**bottom-up on the backend, then bottom-up on the frontend**, so each layer compiles against the one
below it.

## 1. Clarify and scope

- Restate the requirement in one sentence and identify which layers it hits: **DB model? CRUD? API
  route? LangGraph agent? frontend types/api/hooks/components? config/env?**
- Find the closest existing example and mirror it — e.g. a new filter resembles the `is_read` /
  `priority` filters already threaded through `crud.get_articles` → `articles` route → `ArticleFilters`
  type → `useArticles`. Reusing an existing path beats inventing a new shape.
- If the requirement is ambiguous (which model field, which UI surface, admin-only or not), ask before
  building.

## 2. Backend — bottom-up

Implement only the layers the requirement needs, in this order. Each has a governing rule under
`backend/.claude/rules/` — read it first.

1. **Model** (`app/db/models.py`) — add/alter columns following the `db` rule (declarative `Column`,
   `server_default=func.now()`, free-form status strings with inline comments). A schema change to an
   existing table needs a hand-written `backend/migrate_*.py` (SQLite `init_db()` won't alter tables).
2. **CRUD** (`app/db/crud.py`) — add a `db: Session`-first function; this is the single DB-access layer
   both routes and agent nodes call.
3. **Route** (`app/api/routes/*.py`) — add the endpoint with `Depends(get_db)`, Pydantic request/
   response models (`from_attributes = True`), `HTTPException` for 404/400, bounded `Query(...)` params.
   New router → register it in `app/main.py` with `dependencies=auth_dep` unless it's public. See the
   `api-routes` rule.
4. **Agent** (`app/agents/`, `app/services/summary_service.py`) — only if the requirement changes the
   processing pipeline. Nodes return partial state, manage their own `SessionLocal()`, log via
   `crud.create_log`, set `should_continue`, and route LLM calls through `summary_service`. See the
   `langgraph-agent` rule.
5. **Config** (`app/core/config.py`) — new tunable → typed Pydantic field with a default; then mirror it
   into `backend/.env.example` and the Docker env table (see the root `config-and-deploy` rule).

## 3. Frontend — bottom-up

Mirror the backend contract, in this order (rules under `frontend/.claude/rules/`):

1. **Types** (`src/types/index.ts`) — add/extend the interface to match the backend Pydantic response
   exactly. `import type` everywhere.
2. **API layer** (`src/services/api.ts`) — add the call to the matching typed group (`articlesApi`,
   `feedsApi`, ...), returning `response.data`. No `axios` outside this file; auth is interceptor-driven.
3. **Hooks** (`src/hooks/useApi.ts`) — wrap reads in `useQuery`, writes in `useMutation`; use
   array query keys; invalidate every affected key in `onSuccess`. See the `data-fetching` rule.
4. **Component** (`src/components/<Name>/`) — one folder + co-located CSS, typed `interface Props`,
   consume data via hooks (never the api layer directly), German UI text, `date-fns` with `tr` locale.
   See the `components` rule.

## 4. Verify it works

- **Backend:** import-check and run — `cd backend && uvicorn app.main:app --reload`; exercise the new
  endpoint via `http://localhost:8000/docs` or `curl`. Confirm 404/400 paths, not just the happy path.
- **Frontend:** `cd frontend && npm run dev`; drive the actual UI surface. Watch the network tab for the
  `/api` call and React Query cache updates.
- Prefer running the real app over assuming — see the `/run` and `/verify` skills.

## 5. Wrap up

- Run `/update-docs` to sync `README.md` + `backend/.env.example` if you changed behavior, an endpoint,
  config, dependencies, or project structure.
- If you discovered a new recurring convention or gotcha while implementing, capture it with `/add-rule`.
- Don't commit `backend/news_summary.db` or a real `.env`.

## Common mistakes

- **Top-down instead of bottom-up** — building the route before the CRUD/model, or the component before
  the type/api/hook, leaves layers referencing things that don't exist yet.
- **Bypassing the layer** — raw `db.query` in a route, `axios` in a component, or a fetch outside
  `src/services/api.ts`. Go through crud / the api layer / hooks.
- **Forgetting query invalidation** — a mutation that doesn't invalidate the affected `useQuery` keys
  leaves stale UI.
- **Schema change without a migration** — altering an existing table needs a `migrate_*.py`; `init_db()`
  only creates missing tables.
- **Adding a config field in only one place** — `config.py`, `.env.example`, and the Docker env table
  must agree.
- **Skipping verification** — run the app and exercise the change; don't assume it works.
