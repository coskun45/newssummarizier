---
name: implement-requirement
description: Implement a new feature or requirement end-to-end across the Bülten stack (FastAPI backend + React frontend) using a 4-phase lifecycle — analyze, plan & get approval, implement, principal-level review. Use when asked to add a capability, endpoint, field, filter, setting, or UI feature that touches one or both layers.
---

# Implement a Requirement (4-phase lifecycle)

Bülten is a two-service app: a Python **FastAPI** backend (`backend/`) and a **React + Vite +
TypeScript** frontend (`frontend/`), talking over `/api`. Detailed, path-scoped conventions live in
**`.claude/rules/`** and auto-load when you edit matching files — lean on them throughout.

Run the requirement through these **four phases in order**. Do not skip ahead — especially, **do not
write code before the plan is approved (Phase 2)**.

---

## Phase 1 — Requirement analysis

The requirement comes from **the developer's request in this conversation** (no ticket system / file).

- Restate the requirement in one sentence and **discuss it with the developer**: clarify scope,
  acceptance criteria, edge cases, and which surfaces it touches.
- Surface ambiguity explicitly and ask — e.g. which model field, admin-only or all users, which UI
  surface, what happens on empty/error input, backward-compatibility with existing data.
- Identify the affected layers: **DB model? CRUD? API route? LangGraph agent? frontend
  types/api/hooks/components? config/env?**
- Find the closest existing example to mirror (e.g. a new article filter resembles the `is_read` /
  `priority` filters already threaded through `crud.get_articles` → `articles` route →
  `ArticleFilters` type → `useArticles`).

**Do not proceed until the requirement is clearly understood and agreed with the developer.**

## Phase 2 — Plan & get approval

**Do not code yet.** Produce a written implementation plan and **submit it to the developer for
approval**.

The plan should cover:

- The layers to change, in implementation order (backend bottom-up, then frontend bottom-up — see
  Phase 3), with the concrete files/functions touched.
- Data/schema changes and whether a `backend/migrate_*.py` is needed.
- New config/env vars and the three places they must land.
- API contract (endpoint, method, request/response shape) and the matching frontend type.
- Risks, trade-offs, and anything deferred or out of scope.

**Wait for the developer's explicit approval (or requested changes) before Phase 3.** If they ask for
changes, revise the plan and re-submit.

## Phase 3 — Implement

Build the approved plan. Implement only the layers it needs, **bottom-up on the backend, then
bottom-up on the frontend**, so each layer compiles against the one below it.

### Backend (rules under `backend/.claude/rules/`)

1. **Model** (`app/db/models.py`) — declarative `Column`, `server_default=func.now()`, free-form status
   strings with inline comments (`db` rule). Altering an existing table needs a hand-written
   `backend/migrate_*.py` — `init_db()` only creates missing tables.
2. **CRUD** (`app/db/crud.py`) — add a `db: Session`-first function; the single DB-access layer both
   routes and agent nodes call.
3. **Route** (`app/api/routes/*.py`) — `Depends(get_db)`, Pydantic request/response models
   (`from_attributes = True`), `HTTPException` for 404/400, bounded `Query(...)`. New router → register
   in `app/main.py` with `dependencies=auth_dep` unless public (`api-routes` rule).
4. **Agent** (`app/agents/`, `app/services/summary_service.py`) — only if the processing pipeline
   changes. Nodes return partial state, own their `SessionLocal()`, log via `crud.create_log`, set
   `should_continue`, route LLM calls through `summary_service` (`langgraph-agent` rule).
5. **Config** (`app/core/config.py`) — typed Pydantic field with a default; mirror into
   `backend/.env.example` **and** the Docker env table in `README.md` (`config-and-deploy` rule).

### Frontend (rules under `frontend/.claude/rules/`)

1. **Types** (`src/types/index.ts`) — match the backend Pydantic response exactly; `import type`.
2. **API layer** (`src/services/api.ts`) — add to the matching typed group, return `response.data`. No
   `axios` outside this file; auth is interceptor-driven.
3. **Hooks** (`src/hooks/useApi.ts`) — `useQuery` for reads, `useMutation` for writes; array query keys;
   invalidate every affected key in `onSuccess` (`data-fetching` rule).
4. **Component** (`src/components/<Name>/`) — one folder + co-located CSS, typed `interface Props`,
   consume data via hooks (never the api layer directly), German UI text, `date-fns` with `tr` locale
   (`components` rule).

Then **verify it runs**: backend via `uvicorn app.main:app --reload` + `http://localhost:8000/docs` or
`curl` (test 404/400 paths too); frontend via `npm run dev`, driving the real UI and watching the
`/api` call + React Query cache. Prefer the `/run` and `/verify` skills over assuming.

## Phase 4 — Principal-level review

Review your own change as a **principal software engineer** before handing back. Improve **security**
and **code quality**, then re-verify anything you touch.

**Security:**

- **AuthZ/AuthN** — protected routers carry `dependencies=auth_dep`; admin-only actions check
  `require_admin`. No endpoint silently public.
- **Input validation** — bounded/validated `Query`/Pydantic params; reject malformed input with 400,
  don't trust client values.
- **Injection / data exposure** — go through `crud` (parameterized SQLAlchemy), never string-built SQL;
  response models don't leak fields like `hashed_password` or raw internals.
- **Secrets** — nothing hardcoded; keys come from `config.py`/env; no real secret in `.env.example`,
  README, logs, or commits. No secret/PII written to `ProcessingLog`.
- **Frontend** — token handling stays in the axios interceptor; no secret in client code; avoid
  unsanitized `dangerouslySetInnerHTML`.

**Code quality:**

- Follows the layered conventions and the relevant `.claude/rules/` (no `db.query` in routes, no
  `axios` in components, no bypassed layers).
- No duplication — reuse existing crud/api/hooks instead of re-implementing.
- Errors handled, not swallowed; one failure doesn't break a whole agent run (per-article try/except).
- Mutations invalidate the right React Query keys; no stale UI.
- Naming/structure match surrounding code; dead code and debug prints removed.

Fix what you find (or, for anything material, raise it back to the developer). Then run `/code-review`
for an independent pass on the diff.

## Wrap up

- Run `/update-docs` to sync `README.md` + `backend/.env.example` if behavior, an endpoint, config,
  dependencies, or project structure changed.
- Capture any new recurring convention/gotcha with `/add-rule`.
- Don't commit `backend/news_summary.db` or a real `.env`.

## Common mistakes

- **Coding before the plan is approved** — Phase 2 approval is a gate, not a formality.
- **Skipping the requirement discussion** — building the wrong thing fast is still wrong.
- **Top-down instead of bottom-up** — route before crud/model, or component before type/api/hook.
- **Bypassing the layer** — raw `db.query` in a route, `axios` in a component, fetch outside `api.ts`.
- **Forgetting query invalidation** — a mutation that doesn't invalidate leaves stale UI.
- **Schema change without a migration** — altering an existing table needs a `migrate_*.py`.
- **Treating Phase 4 as optional** — the security + quality review is part of the lifecycle.
