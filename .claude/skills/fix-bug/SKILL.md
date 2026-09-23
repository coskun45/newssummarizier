---
name: fix-bug
description: Fix a bug in the Bülten stack (FastAPI backend and/or React frontend) test-first — reproduce it, write a regression test that fails against the buggy code, fix the root cause, then prove the test passes. Use when asked to fix a bug, error, crash, wrong behavior, regression, or a failing flow ("X doesn't work", "hata", "düzelt").
---

# Fix a Bug (test-first)

`CLAUDE.md` makes a regression test mandatory for every fix. This skill is the order that makes
that test meaningful: **the test must be seen failing against the old code before the fix**, or it
proves nothing. Path-scoped rules in `.claude/rules/`, `backend/.claude/rules/`,
`frontend/.claude/rules/` auto-load as you touch files — follow them.

## 1. Reproduce and locate

- Restate the bug in one sentence: **expected vs. actual**, and where it shows (endpoint, UI flow,
  pipeline stage, bulletin, playground).
- Reproduce it before reading code deeply — a failing `curl`/`pytest` call, the UI flow, or the log
  line. If you can't reproduce it, say so and ask for the missing input (data, steps, environment)
  instead of guessing a fix.
- Find the **root cause**, not the first place the symptom surfaces. Walk the layers: model → crud →
  route → agent/service on the backend; types → `api.ts` → `useApi.ts` → component on the frontend.
  A wrong value in the UI is often a wrong query, a missing React Query invalidation, or a
  `mockApi.ts` that drifted from the backend.
- If the cause is ambiguous, or the correct fix changes an API contract / stored data / user-visible
  behavior, **stop and confirm the intended behavior with the developer** before writing the fix.

## 2. Write the failing regression test first

Pick the layer where the bug actually lives:

- **Backend** → `backend/tests/test_<router-or-module>.py` (extend the existing file when there is
  one). Use the `client` + `auth_headers`/`admin_headers` fixtures and the `_make_*` row builders from
  `conftest.py`; stub OpenAI/scraping with `monkeypatch` — tests never hit the network.
- **Frontend** → `frontend/tests/<flow>.spec.ts` with `loginAs` + `mockApi` from `tests/helpers/`,
  asserting user-visible behavior (`getByRole`, visible text). If the bug is in how the UI reacts to
  a backend response, feed that exact response through `mockApi` overrides.
- **Both layers wrong** → one test per layer.

Name the test after the behavior, not the ticket (`test_reprocess_keeps_error_group_on_failure`,
not `test_bug_42`). Then **run it and confirm it fails for the bug's reason** — an import error,
typo or missing fixture is not a reproduction:

```bash
cd backend && pytest -q tests/test_<file>.py -k <name>
cd frontend && npx playwright test tests/<flow>.spec.ts
```

Only skip the test when the change is truly untestable (comment/typo); say so explicitly.

## 3. Fix the root cause

- Smallest change that fixes the cause, in the layer that owns it — keep the layering rules (no
  `db.query` in routes, no `axios` in components, OpenAI only via `summary_service.py`).
- Don't bundle unrelated refactors into a fix; note them for later instead.
- If the fix changes a backend response the frontend mocks, update `frontend/tests/helpers/mockApi.ts`
  in the same change so the mock keeps mirroring the backend.

## 4. Prove it

1. The new test now passes.
2. The whole affected suite still passes: `cd backend && pytest -q` and/or
   `cd frontend && npm run test:e2e`.
3. Lint is clean (the edit hook runs ruff/eslint; CI runs `ruff check app/` and `npm run lint`).
4. Re-run the original reproduction from step 1 (curl / UI / log) and see it behave correctly.

Report the failing-then-passing test output — don't just claim it.

## 5. Wrap up

- **`features.json`**: a pure fix doesn't touch it. If the push hook blocks because feature files
  changed, and nothing user-facing changed, re-run the push with ` # features-ok` appended. If the fix
  *did* change what a feature does, update its description instead.
- **Docs**: a fix that removes a failure mode users/operators hit may deserve a `## 🐛 Sorun Giderme`
  entry in `README.md` — `/update-docs` handles that before the PR.
- **Recurring gotcha?** If this class of bug can happen again (a trap in a convention), record it with
  `/add-rule`.
- Commit as `fix: <what was wrong>` — test and fix in the same commit.

## Common mistakes

- **Writing the test after the fix** — then you never saw it fail, and it may not reproduce the bug.
- **A test that fails for the wrong reason** (import error, bad fixture) counted as a reproduction.
- **Patching the symptom** — e.g. hiding a `None` in the component while the crud query is wrong.
- **Mocking the thing under test** — stub OpenAI/network, not the function you are fixing.
- **Letting `mockApi.ts` drift** — the e2e suite then passes against a backend that no longer exists.
- **Skipping the full suite** — a fix in `crud.py` or `summary_service.py` has many callers.
