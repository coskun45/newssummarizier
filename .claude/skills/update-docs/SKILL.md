---
name: update-docs
description: Bring the project docs up to date before a PR. Diffs the current branch against the integration branch and maps the changes onto README.md (features, API endpoints, config, project structure, troubleshooting) and backend/.env.example, then verifies the docs against the actual code. Use before creating a PR, or whenever asked to "update the docs" / "sync documentation" for a change.
---

# Update Documentation

This project (Bülten) has a **single documentation surface**: the root **`README.md`** (Turkish),
backed by **`backend/.env.example`** as the environment-variable reference. There is no MkDocs site,
no public/internal split, and no doc validator — so "update the docs" means keeping `README.md` and
`.env.example` consistent with the code on this branch.

Execute the steps in order. You own the final wording — keep the README's **Turkish** voice, emoji
section headers, and table style.

## 1. Determine what changed

```bash
git fetch origin --quiet
git diff --name-status origin/master...HEAD   # files changed on this branch
git diff origin/master...HEAD                 # full diff when you need the detail
```

Use whichever branch you actually merge into as the base (`master` is the default integration branch;
`production` / `azure-deploy` are deploy branches). Then classify each change:

- **User- or operator-meaningful** — a new/changed feature, API endpoint, config/env var, dependency,
  setup step, project-structure change, or a fix that introduces/removes a failure mode. **Needs a doc
  update.**
- **Internal-only** — refactor, rename, test, or formatting with no behavior/config/interface change.
  **No doc update**; just note it.

If the whole branch is internal-only, there is nothing to document — say so and move on.

## 2. Map the change onto the right README section

`README.md` has stable sections; route each change to the matching one:

| Change | README section |
|---|---|
| New/changed capability | `## 🎯 Özellikler` (and `## 🏗️ Mimari` if it's architectural) |
| New/changed/removed API endpoint | `## 📖 Kullanım → ### API Endpoints` |
| New/changed env var or limit | `## ⚙️ Yapılandırma → ### Backend (.env)` **and** the Docker env table under `## 🐳 Docker → ### Ortam Değişkenleri` |
| New runtime dependency | `## 🛠️ Teknoloji Yığını` |
| New/renamed directory or file | the **two** `Proje Yapısı` trees (one under `## 🐳 Docker`, one under `## 📁 Proje Yapısı`) — keep both in sync |
| Changed setup/run/build flow | `## 🚀 Kurulum`, `## 🎮 Uygulamayı Başlatma`, or `## 🐳 Docker` |
| New failure mode or a bug fix worth a runbook | `## 🐛 Sorun Giderme` (symptom → cause → fix, matching the existing format) |

- **Document only what changed.** Don't rewrite untouched sections.
- **Endpoint docs are illustrative, not exhaustive** — the README lists representative endpoints, not
  every route. Add an endpoint here only if it's a primary, user-facing one; the live source of truth
  is `http://localhost:8000/docs` (auto-generated OpenAPI). Don't try to mirror every route.

## 3. Sync the env-var reference (`backend/.env.example`)

Any new or renamed setting in `backend/app/core/config.py` MUST appear in **`backend/.env.example`**
with a safe placeholder (never a real key/secret), and — if operators set it — in the README's `.env`
block and the Docker env table. These three must agree. Mark anything you can't confirm as
`# TODO: verify` rather than inventing a default.

## 4. Verify the docs against the code

There is no automated validator, so check by hand against the source of truth:

- **Env vars:** every key in the README `.env` block / Docker table exists as a field in
  `backend/app/core/config.py` (or `docker-compose.yml`), and vice-versa for newly added ones.
- **API endpoints:** documented paths match `backend/app/api/routes/*.py` + the prefixes in
  `app/main.py` (e.g. summaries mount at bare `/api`). See the backend `api-routes` rule.
- **Project-structure trees:** the folders shown actually exist; both trees match.
- **Commands & ports:** run/Docker commands and ports (8000 backend, 5173 dev, 80 Docker) are current.
- **Markdown sanity:** links resolve, tables render, fenced code blocks are closed.

Fix every mismatch you find before handing back.

## 5. Hand back for review

Summarize what you changed in `README.md` and `.env.example` and why, and flag anything you marked
`# TODO: verify` so the human can confirm an exact key or default. The PR can then be created.

## Common mistakes

- **Updating only one of the two `Proje Yapısı` trees** — there are two (Docker section + bottom); keep
  them identical.
- **Adding an env var to the README but not `backend/.env.example`** (or vice-versa), or not to the
  Docker env table — all three must agree.
- **Putting a real API key / secret in `.env.example` or the README** — always use a placeholder.
- **Switching the README to English** — it is Turkish; match the existing language, emoji headers, and
  table style.
- **Trying to list every API route** — the endpoint section is curated and representative; the OpenAPI
  page at `/docs` is the exhaustive reference.
- **Documenting an internal-only refactor** — if nothing about behavior, config, or interface changed,
  there's nothing to write.
