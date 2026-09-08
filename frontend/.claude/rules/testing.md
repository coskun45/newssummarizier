---
paths:
  - "src/**"
  - "tests/**"
---

# Frontend Tests (Playwright e2e)

## Required for every feature
- **Every new/changed component or user flow gets an e2e spec in `frontend/tests/`** — see
  [[components]]. A feature isn't done after a manual click-through; it's done when a spec fails if
  the behavior regresses. Name the file after the flow, not the component (`login.spec.ts`, not
  `Login.spec.ts`).
- **Assert on user-visible behavior** — `page.getByRole(...)`/`getByLabel(...)`/visible text — not on
  CSS classes or implementation details, so the test survives styling/refactors.

## Config (`playwright.config.ts`)
- **`baseURL` and `webServer` point at the fixed Vite dev port (`5174` from `vite.config.ts`)** and
  auto-start `npm run dev`. Don't hardcode a different port or assume a server is already running.
- **Prefer specs that don't require the backend** when the flow allows it (e.g. the logged-out
  `<Login/>` shell renders from `localStorage` state alone — see `App.tsx`). If a flow genuinely needs
  live data, say so in the spec and gate it appropriately rather than let it silently depend on
  `http://localhost:8000` being up.

## Running
- `cd frontend && npm run test:e2e` (wraps `playwright test`).
