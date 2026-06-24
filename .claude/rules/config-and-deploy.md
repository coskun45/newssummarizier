---
paths:
  - "backend/app/core/config.py"
  - "backend/.env.example"
  - "backend/Dockerfile"
  - "frontend/Dockerfile"
  - "frontend/nginx.conf"
  - "frontend/vite.config.ts"
  - "docker-compose.yml"
  - "deploy.sh"
  - ".github/workflows/**"
---

# Configuration & Deployment

This is a two-service app: a Python **FastAPI** backend (`backend/`) and a **React + Vite** frontend (`frontend/`), shipped via Docker and a GitHub Actions pipeline.

## Configuration
- **Backend config is Pydantic `BaseSettings`** in `backend/app/core/config.py`, loaded from env / `.env`. Add a new setting as a typed field with a sensible default — then document it in `backend/.env.example`. The single required (no-default) field is `openai_api_key`.
- **NEVER hardcode secrets** — `jwt_secret_key`, `openai_api_key`, and DB URLs come from env. The default JWT secret is a dev placeholder and must be overridden in production.
- **CORS origins are a comma-separated env string**, parsed by `settings.cors_origins_list`. Update this (not hardcoded lists) when adding a frontend origin.

## Frontend ↔ backend contract
- **Frontend talks to `/api` only** — the dev server proxies it (`vite.config.ts`) and prod serves it via `frontend/nginx.conf`. Keep new endpoints under `/api` so both proxies route them.
- **CI sets a dummy `OPENAI_API_KEY`** for the FastAPI import check (config requires it). Preserve that step or the import check fails.

## Deploy
- **Health check is `/api/health`** (also `/health`) — referenced by the docker smoke test. Don't remove it.
- **Changes to build/deploy go through the existing pipeline** (`.github/workflows/`, `deploy.sh`, `docker-compose.yml`); don't introduce a parallel deploy path.
