---
paths:
  - "src/components/**"
  - "src/types/**"
---

# React Components

## Structure
- **One component per folder, co-located with its CSS** — `src/components/<Name>/<Name>.tsx` + `<Name>.css`, imported as `import './<Name>.css'`. Follow this layout for every new component. Exception: shared design tokens and generic UI primitives (buttons, badges, inputs, modal shell, skeletons) live in `src/styles/` instead — see [[styling]].
- **Components are typed function declarations** with an explicit `interface <Name>Props` and default values in the destructured params (`function ArticleCard({ article, isSelected = false }: ArticleCardProps)`). Default-export the component.
- **Domain types live in `src/types/index.ts`** — import them with `import type { ... }`. Don't redefine API shapes locally; keep them in sync with the backend Pydantic response models (see backend `api-routes`).

## Data & state
- **Fetch through hooks, never the api layer directly** — components call `useArticles`, `useSummary`, etc. from `src/hooks/useApi.ts` (see [[data-fetching]]). No `axios`/`fetch` in components.
- **Local UI state uses `useState`; server state belongs to React Query** — don't cache server responses in component state.
- **Gate expensive fetches behind UI state** by passing `null`/conditional ids into hooks (`useSummary(expanded ? article.id : null, ...)`), relying on the hook's `enabled` guard.
- **Render cached `data` before checking `isError`** — when a background refetch (`refetchInterval`) fails, React Query sets `isError` but keeps the last good `data`, so `isError || !data ? <error/> : …` swaps a working view for an error. Show the full error state only when there is no `data` (see `Analysis.tsx`).

## i18n / formatting
- **UI text is Turkish** — match the existing language of labels and buttons.
- **Format dates with `date-fns` using the `tr` locale** (`formatDistanceToNow(date, { addSuffix: true, locale: tr })`) as established in `ArticleCard`.
- **Format API day keys (`"2026-10-16"`, the UTC days of the `/stats/*` endpoints) with `format(parseISO(day), …)`, NEVER ``new Date(`${day}T00:00:00Z`)``** — that is UTC midnight, which `format` renders in local time as the previous day west of UTC; `parseISO` reads a date-only string as local midnight, so the label is the API's day in every timezone (see `PriorityTrendChart`).
