# CLAUDE.md

Bülten — an AI news aggregator: it pulls Deutsche Welle (DW) RSS feeds, scrapes full article
content, classifies + prioritizes articles, and generates brief/standard/detailed summaries with
OpenAI. Two services talking over `/api`:

- **Backend** (`backend/`) — Python **FastAPI** + **LangGraph** agent pipeline + **SQLAlchemy/SQLite** + OpenAI.
- **Frontend** (`frontend/`) — **React 18 + TypeScript + Vite**, data via **TanStack Query** over **axios**.

User-facing language is **Turkish/German** — keep UI text and `README.md` in their existing language.

## Layout

```
backend/app/
  agents/      LangGraph workflow: graph.py, nodes.py, state.py, tools.py
  api/         routes/ (FastAPI routers) + deps.py (JWT auth) ; mounted in main.py
  core/        config.py (Pydantic settings), exceptions.py, security.py
  db/          models.py, crud.py (single DB-access layer), database.py, seed.py
  services/    summary_service.py (all OpenAI calls)
  tasks/       scheduler.py + background.py (periodic feed processing)
frontend/src/
  components/  one folder + co-located .css per component
  hooks/       useApi.ts (React Query hooks)
  services/    api.ts (typed axios layer)
  types/       index.ts (shared types, mirror backend Pydantic responses)
```

## Common commands

```bash
# Backend
cd backend && uvicorn app.main:app --reload      # http://localhost:8000  (docs at /docs)
# Frontend
cd frontend && npm run dev                        # http://localhost:5173
# Full stack via Docker
docker compose up --build                         # http://localhost  (API at /api)
```

`OPENAI_API_KEY` is required (see `backend/.env.example`). SQLite DB is `backend/news_summary.db`.

## Architecture rules

Detailed, path-scoped conventions live in **`.claude/rules/`** (auto-loaded when you edit matching
files). The essentials:

- **Backend is layered: model → crud → route.** Routes use `Depends(get_db)` and go through
  `app.db.crud`; never raw `db.query` in handlers. Agent nodes are the only code that opens its own
  `SessionLocal()`. All OpenAI calls go through `services/summary_service.py`.
- **All routers except `auth` require JWT** (`dependencies=auth_dep` in `main.py`).
- **Schema changes need a hand-written `backend/migrate_*.py`** — `init_db()` only creates missing tables.
- **Frontend never calls `axios`/endpoints directly** — go types → `services/api.ts` → `hooks/useApi.ts`
  → component. Mutations must invalidate the affected React Query keys.
- **Config lives in three places that must agree:** `core/config.py`, `backend/.env.example`, and the
  Docker env table in `README.md`.

## Workflow

- **New feature/requirement** → follow the `/implement-requirement` skill (bottom-up across layers).
- **Learned a new recurring convention/gotcha** → record it with the `/add-rule` skill into
  `.claude/rules/` (do not bloat this file).
- **Before a PR** → run the `/update-docs` skill to sync `README.md` + `backend/.env.example`.
- **Don't commit** `backend/news_summary.db` or a real `.env`.
