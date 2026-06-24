---
paths:
  - "src/services/**"
  - "src/hooks/**"
---

# Data Fetching (axios + React Query)

## API layer (`src/services/api.ts`)
- **Components NEVER import `axios` or call endpoints directly** — every HTTP call goes through a typed group in `src/services/api.ts` (`articlesApi`, `feedsApi`, `topicsApi`, ...). Add new endpoints there and return `response.data` typed against `src/types`.
- **Base URL is `/api`** (proxied by Vite/nginx) — never hardcode hostnames.
- **Auth is handled by interceptors, not callers** — the request interceptor injects the `auth_token` from `localStorage`; the response interceptor clears the session and dispatches a `auth:logout` window event on 401. Don't add per-call token handling or 401 checks.

## Hooks (`src/hooks/useApi.ts`)
- **Components consume data through `useXxx` hooks in `useApi.ts`, not by calling the api layer directly.** Reads use `useQuery`, writes use `useMutation`.
- **Query keys are arrays prefixed by entity** (`['articles', filters]`, `['article', id]`, `['topics', feedId]`). Match this so invalidation stays predictable.
- **Mutations invalidate every affected query in `onSuccess`** — e.g. marking read invalidates both `['articles']` and `['articleCounts']`; deleting a feed also invalidates `['articles']`. Forgetting an invalidation leaves stale UI.
- **Immutable data uses `staleTime: Infinity`** (summaries never change). List data that the background scheduler mutates uses `refetchInterval: 60000` so new articles appear without a manual refresh.
- **Disable dependent queries until inputs exist** with `enabled: id !== null` and the non-null assertion in `queryFn` (`articlesApi.get(id!)`).
