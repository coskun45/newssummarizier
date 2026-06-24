---
paths:
  - "src/components/**"
  - "src/types/**"
---

# React Components

## Structure
- **One component per folder, co-located with its CSS** — `src/components/<Name>/<Name>.tsx` + `<Name>.css`, imported as `import './<Name>.css'`. Follow this layout for every new component.
- **Components are typed function declarations** with an explicit `interface <Name>Props` and default values in the destructured params (`function ArticleCard({ article, isSelected = false }: ArticleCardProps)`). Default-export the component.
- **Domain types live in `src/types/index.ts`** — import them with `import type { ... }`. Don't redefine API shapes locally; keep them in sync with the backend Pydantic response models (see backend `api-routes`).

## Data & state
- **Fetch through hooks, never the api layer directly** — components call `useArticles`, `useSummary`, etc. from `src/hooks/useApi.ts` (see [[data-fetching]]). No `axios`/`fetch` in components.
- **Local UI state uses `useState`; server state belongs to React Query** — don't cache server responses in component state.
- **Gate expensive fetches behind UI state** by passing `null`/conditional ids into hooks (`useSummary(expanded ? article.id : null, ...)`), relying on the hook's `enabled` guard.

## i18n / formatting
- **UI text is German** — match the existing language of labels and buttons.
- **Format dates with `date-fns` using the `tr` locale** (`formatDistanceToNow(date, { addSuffix: true, locale: tr })`) as established in `ArticleCard`.
