---
paths:
  - "src/styles/**"
  - "src/components/**"
  - "src/contexts/**"
---

# Design Tokens & Shared UI Primitives

## `src/styles/` is an intentional exception to "co-located CSS per component"

- **`src/styles/tokens.css`** holds every color/spacing/radius/shadow as a CSS custom property.
  Light values are on `:root`; dark overrides live under `:root[data-theme='dark']`. The
  `data-theme` attribute is set on `<html>` by `ThemeProvider` (`src/contexts/ThemeContext.tsx`),
  which resolves `light`/`dark`/`system` and persists the user's choice in localStorage
  (`bulten_theme`). **Never hardcode a hex color in component CSS** — use a `var(--color-*)`
  token so light/dark and future palette changes stay centralized. Both files are imported once
  in `main.tsx`, before `index.css`.
- **`src/styles/base.css`** holds truly shared primitives: `.btn`/`.btn-primary`/`.btn-secondary`/
  `.btn-outline`/`.btn-danger`/`.btn-sm`/`.btn-lg`/`.btn-icon`, `.badge`, `.input`/`.select`/
  `.textarea`, the modal shell (`.modal-overlay`, `.modal-shell`, `.modal-shell-header`,
  `.modal-shell-body`, `.modal-shell-footer`, `.modal-close-btn`), and `.skeleton` loading blocks.
  Component stylesheets should use these classes instead of redefining button/badge/input/modal/
  skeleton styles locally — this replaced several near-duplicate `.btn`/`.btn-primary` blocks that
  had drifted out of sync across `ArticleCard.css`, `Dashboard.css`, `Settings.css`, etc.

## When to add a new primitive vs. keep it co-located

- **Add to `base.css`** only when at least two components need the same generic UI pattern
  (a button variant, a form field, a modal shell). Give it a generic, reusable class name.
- **Keep it in the component's own CSS** for anything specific to that component's layout or a
  one-off look — `base.css` is for cross-cutting primitives, not a dumping ground.
- See also [[components]] for the general co-located-CSS convention this exception carves out of.
