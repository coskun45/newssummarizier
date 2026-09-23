---
paths:
  - "frontend/src/data/features.json"
  - "frontend/src/components/**"
  - "frontend/tests/features-tab.spec.ts"
  - "backend/app/api/routes/**"
  - "backend/app/agents/**"
  - "backend/app/tasks/**"
  - "backend/app/services/**"
---

# Features list (`features.json`)

`Ayarlar › Features` (`frontend/src/components/Features/Features.tsx`) renders **`frontend/src/data/features.json`** —
the single source of truth for "what the app can do", organized **by version**. It is hand-maintained, so it only
stays correct if it is updated in the same change that alters a feature.

## When to update
- **Feature added → add an entry under the right version in the same change** — a new user-facing capability
  (component, filter, endpoint, setting, background job, pipeline stage) is not done until it is listed.
- **Feature removed → delete its entry**; **renamed/behavior changed → edit its `title`/`description`**.
  A stale entry misleads users more than a missing one.
- Pure refactors, bug fixes and styling changes don't touch the file.
- **Enforced on push** by `.claude/hooks/check_features_json.py` — as a Claude `PreToolUse` hook and in the
  local `.git/hooks/pre-push` (manual pushes): if files under the `paths:` above changed but `features.json`
  didn't, the push is stopped. Update the file, or — for a fix/refactor only — push with `FEATURES_OK=1 git push`
  (PowerShell: `$env:FEATURES_OK=1; git push`).
- When following `/implement-requirement`, do this in the implement phase; before a PR, `/update-docs` should
  find `features.json` consistent with `README.md` (Özellikler) — see the frontend `components` rule (`frontend/.claude/rules/components.md`).

## Versions
- **`v1` = Temel haber özetleme** (RSS → scrape → classify → brief/standard/detailed summaries, news UI, feeds,
  topics, summary types, auth, scheduler). **`v2` = Bülten ve Playground** (Word bulletin, Playground, and the
  features tied to them, e.g. system prompts, this Features page).
- **A new feature goes into the latest version** unless the user says it starts a new one. When the user starts a
  new version, append a `{ "version": "vN", "title": "…", "features": [] }` object at the end — never renumber or
  move existing entries between versions unless asked.

- **The highest `vN` is the app's major version.** `scripts/next_version.py` (called by the deploy job in
  `ci-cd.yml`) builds `N.<minor>.0`: minor auto-increments per deploy from the `vX.Y.Z` git tags, and appending a new
  `vN` block makes the next deploy `N.0.0`. So only add a `vN` block when the user actually wants a major release.
  The running version is shown in the profile menu that opens from the avatar (`UserMenu`) and on this page, fed by `/api/info`.

## Schema (`FeaturesData` in `src/types/index.ts`)
```json
{ "versions": [ { "version": "v1", "title": "Temel haber özetleme",
    "features": [ { "id": "article-list", "title": "…", "description": "…" } ] } ] }
```
- **`version` is `v<number>` and unique**; `title` names the version's theme. The page renders the **newest
  version first** (sorted by number, not array order), so keep the array in ascending order and append new versions.
- **Feature `id` is unique kebab-case across all versions** — it is the React key; `features-tab.spec.ts` fails on
  duplicates or bad format.
- **`title`/`description` are Turkish** (the UI language), one or two sentences describing what the *user* gets,
  not implementation detail.
- **A feature has exactly `id`, `title`, `description`** — no code paths or locations in the data; the spec rejects
  extra keys.

## Tests
- **`frontend/tests/features-tab.spec.ts` reads the same JSON** and asserts every version heading, feature title
  and description is rendered, so a malformed entry fails `npm run test:e2e`. Don't hardcode feature titles in the spec.
