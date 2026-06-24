---
paths:
  - "app/db/**"
---

# Database (SQLAlchemy + SQLite)

## Models
- **ALL models subclass `Base` from `app.db.database`** and live in `app/db/models.py`. Use `Column(...)` declarative style (not 2.0 `Mapped[]`) to match existing models.
- **Use `server_default=func.now()` for created timestamps** and add `onupdate=func.now()` for `updated_at` columns — don't set timestamps in Python.
- **Child relationships that should die with the parent use `cascade="all, delete-orphan"`** (see `Feed.articles`, `Article.summaries/topics/logs`). Many-to-many link rows (`ArticleTopic`) carry extra columns like `confidence` — model them as an explicit association class, not a bare `Table`.
- **`status`/`importance`/`priority` are free-form `String` columns**, not enums. Valid values are documented in inline comments (`pending|scraped|summarized|failed|filtered`, `important|unimportant`, `high|med|low`). Keep those comments in sync when adding a state.

## CRUD layer
- **ALWAYS add new query/mutation logic to `app/db/crud.py`** as a standalone function taking `db: Session` first — routes and agent nodes both depend on this single layer (see [[api-routes]], [[langgraph-agent]]).
- **CRUD functions commit their own writes.** Callers don't manage transactions beyond passing the session.

## Migrations
- **SQLite has no migration framework here** — schema changes are applied by hand-written scripts at the repo root (`backend/migrate_*.py`). When you add/rename a column, write a matching `migrate_*.py` script; `init_db()` only `create_all`s missing tables, it does NOT alter existing ones.
- **NEVER commit a populated `news_summary.db`** as part of a feature — it's a local dev artifact.
