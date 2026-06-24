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
- **Column adds are handled in code, not scripts.** `create_all()` only creates missing tables (never alters existing ones), so `init_db()` in `db/database.py` runs an idempotent auto-migration: it ALTER-adds any missing column listed in `article_columns`. When you add a column to a model, also append `(name, DDL)` there — existing SQLite DBs get patched on next startup, no manual step.
- **More complex changes** (renames, type changes, drops, data backfills) aren't covered by the column loop — write a one-off `backend/migrate_*.py` for those (e.g. `migrate_remove_german_topics.py`) and run it manually.
- **NEVER commit a populated `news_summary.db`** (or any `*.db`) — local artifact, gitignored.
