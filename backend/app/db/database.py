"""
Database connection and session management.
"""
from datetime import timezone
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator, DateTime as _DateTime, Text as _Text
from app.core.config import settings

_is_sqlite = "sqlite" in settings.database_url


def _engine_kwargs(database_url: str) -> dict:
    """Engine options. For PostgreSQL this is the safety net against pool exhaustion:
    pre-ping drops dead connections, a short pool_timeout fails a request fast instead of
    stalling a worker, and server-side timeouts make PostgreSQL itself end a statement or an
    abandoned "idle in transaction" session that would otherwise pin a pooled connection forever.
    """
    if "sqlite" in database_url:
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": 10,
        "max_overflow": 10,
        "pool_timeout": 10,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
        "connect_args": {
            "options": "-c statement_timeout=120000 -c idle_in_transaction_session_timeout=600000",
        },
    }


# Create database engine
engine = create_engine(settings.database_url, **_engine_kwargs(settings.database_url))

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        """WAL lets readers and writers proceed concurrently instead of blocking on the
        default rollback-journal lock; busy_timeout makes a writer wait for a released lock
        instead of failing immediately with 'database is locked' under concurrent access
        (interactive requests vs. the hourly background feed refresh)."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create declarative base
Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """DateTime that always round-trips as timezone-aware UTC.

    SQLite has no native timezone-aware storage - SQLAlchemy's DateTime silently
    drops tzinfo on write and never restores it on read. This normalizes any
    incoming aware datetime to UTC before storage and re-attaches UTC tzinfo on
    read, so every value flowing through the ORM is unambiguous UTC end-to-end.
    """
    impl = _DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class EmbeddingVector(TypeDecorator):
    """An embedding: pgvector's `vector(dim)` on PostgreSQL, JSON text on SQLite (the tests) — and
    on a PostgreSQL without pgvector, where the tables must still exist so article deletes (which
    cascade into them) keep working. Python values are lists of floats either way."""
    impl = _Text
    cache_ok = True

    def __init__(self, dimensions: int):
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if _uses_pgvector(dialect):
            from pgvector.sqlalchemy import Vector
            return dialect.type_descriptor(Vector(self.dimensions))
        return dialect.type_descriptor(_Text())

    def process_bind_param(self, value, dialect):
        if value is None or _uses_pgvector(dialect):
            return value
        import json
        return json.dumps([float(v) for v in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if _uses_pgvector(dialect):
            return [float(v) for v in value]
        import json
        return json.loads(value)


# Tables with EmbeddingVector columns.
VECTOR_TABLES = ("article_chunk_embeddings",)
# Whether vector search can run: pgvector installed (PostgreSQL) — set by init_db(). SQLite (the
# tests) always can: similarity is computed in Python there.
vector_support = {"available": _is_sqlite, "reason": None}


def _uses_pgvector(dialect) -> bool:
    return dialect.name == "postgresql" and vector_support["available"]


def release_connection(db: Session) -> None:
    """End the session's current transaction so its pooled connection goes back to the pool.

    Call it right before a long `await` (scraping, OpenAI) in background code: a session keeps
    its connection checked out ("idle in transaction") from its first query until commit — a
    read, or the `db.refresh()` in every crud create, is enough to re-open one. crud writes
    commit themselves, so this only closes that implicit read transaction; loaded objects are
    expired and reload on next access, so read what the await needs into locals first.
    """
    db.commit()


def get_db():
    """
    Dependency for getting database session.
    Use with FastAPI Depends().
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# The only relations the Asistan's SQL tool may read (app/agents/analysis/sql_guard.py enforces it,
# the read-only role below backs it up on PostgreSQL). `is_analyzable` is the Analiz tab's rule —
# a high/med/low label, not Önemsiz, not Error (crud.get_analysis_stats); a label means the
# article is not "unlabelled", so the Error part reduces to status 'failed'.
CHAT_VIEWS = {
    "chat_articles": """
        SELECT a.id, a.title, a.published_at, a.fetched_at,
               COALESCE(a.published_at, a.fetched_at) AS article_date,
               a.priority, a.importance, a.is_starred, a.is_read, a.status,
               a.feed_id, f.title AS feed_title,
               CASE WHEN a.priority IN ('high', 'med', 'low')
                         AND (a.importance IS NULL OR a.importance <> 'unimportant')
                         AND a.status <> 'failed'
                    THEN TRUE ELSE FALSE END AS is_analyzable
        FROM articles a JOIN feeds f ON f.id = a.feed_id
    """,
    "chat_article_topics": """
        SELECT at.article_id, at.topic_id, t.name AS topic_name, at.confidence
        FROM article_topics at JOIN topics t ON t.id = at.topic_id
    """,
    "chat_summaries": """
        SELECT s.article_id, s.summary_type, s.summary_text, s.created_at
        FROM summaries s
    """,
}
# NOLOGIN role the Asistan's queries switch to (SET LOCAL ROLE) — it can read the views only.
CHAT_READONLY_ROLE = "bulten_chat_ro"


def create_chat_views(bind) -> None:
    """(Re)create the Asistan's SQL views, and on PostgreSQL the read-only role allowed to read
    only them. Idempotent; runs on every startup (and in the tests on their SQLite engine)."""
    from sqlalchemy import text
    is_postgres = bind.dialect.name == "postgresql"
    with bind.connect() as conn:
        for name, query in CHAT_VIEWS.items():
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
            conn.execute(text(f"CREATE VIEW {name} AS {query}"))
        if is_postgres:
            conn.execute(text(
                f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{CHAT_READONLY_ROLE}') "
                f"THEN CREATE ROLE {CHAT_READONLY_ROLE} NOLOGIN; END IF; END $$"
            ))
            conn.execute(text(f"GRANT {CHAT_READONLY_ROLE} TO CURRENT_USER"))
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {CHAT_READONLY_ROLE}"))
            conn.execute(text(f"GRANT SELECT ON {', '.join(CHAT_VIEWS)} TO {CHAT_READONLY_ROLE}"))
        conn.commit()


_VECTOR_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_article_chunk_embeddings_hnsw ON article_chunk_embeddings "
    "USING hnsw (embedding vector_cosine_ops)",
    # Keyword half of the hybrid search; 'simple' because texts are German, English and Turkish.
    "CREATE INDEX IF NOT EXISTS ix_article_chunk_embeddings_fts ON article_chunk_embeddings "
    "USING gin (to_tsvector('simple', text))",
)


def _ensure_vector_extension() -> None:
    """Enable pgvector. Without it (a DB image lacking the extension) the app still starts: the
    embedding tables are skipped and vector search reports itself unavailable."""
    if _is_sqlite:
        return
    import logging
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        vector_support.update(available=True, reason=None)
    except Exception as e:
        vector_support.update(
            available=False,
            reason="Veritabanında pgvector eklentisi yok — DB'yi docker/postgres imajıyla yeniden başlatın.",
        )
        logging.getLogger(__name__).warning(f"pgvector unavailable, vector search disabled: {e}")


def _drop_text_fallback_vector_tables() -> None:
    """pgvector became available on a DB whose embedding tables were created without it (text
    columns, necessarily empty — nothing is embedded without pgvector): drop them so create_all
    rebuilds them with real vector columns."""
    if _is_sqlite or not vector_support["available"]:
        return
    from sqlalchemy import text
    with engine.connect() as conn:
        for table in VECTOR_TABLES:
            udt = conn.execute(text(
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = 'embedding'"
            ), {"t": table}).scalar()
            if udt is not None and udt != "vector":
                conn.execute(text(f"DROP TABLE {table}"))
        conn.commit()


def init_db():
    """Create tables and apply lightweight, idempotent column migrations.

    SQLAlchemy's create_all() creates missing tables but never alters existing
    ones. So when a new column is added to a model, we also add it here for
    databases created before the change — runs on every startup, no separate
    migrate_*.py scripts needed. Fresh databases already get every column from
    create_all(), so the loop simply finds nothing to do.
    """
    from sqlalchemy import text, inspect
    _ensure_vector_extension()
    _drop_text_fallback_vector_tables()
    Base.metadata.create_all(bind=engine)

    # (column, DDL) to ensure on the articles table. Add a line here whenever a
    # new column is introduced on the Article model.
    article_columns = [
        ("importance", "VARCHAR"),
        ("priority", "VARCHAR"),
        ("is_read", "BOOLEAN NOT NULL DEFAULT false"),
        ("is_starred", "BOOLEAN NOT NULL DEFAULT false"),
        ("image_url", "VARCHAR"),
        ("feed_author", "VARCHAR"),
    ]
    # Same for the other tables — add the table here when one of its models gains a column.
    group_fk = "INTEGER REFERENCES item_groups(id) ON DELETE SET NULL"
    table_columns = {
        "articles": article_columns,
        "feeds": [("group_id", group_fk)],
        "topics": [("group_id", group_fk)],
        "newsletter_subscriptions": [("summary_type", "VARCHAR NOT NULL DEFAULT 'stored'")],
    }

    inspector = inspect(engine)
    with engine.connect() as conn:
        for table, columns in table_columns.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for column, ddl in columns:
                if column not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                        conn.commit()
                    except Exception:
                        # On strict-transaction dialects (Postgres), a failed statement
                        # leaves the connection's transaction "aborted" until an explicit
                        # rollback — every later statement on this same conn (remaining
                        # ALTERs, the CREATE INDEX below) would otherwise raise
                        # "current transaction is aborted" too and get silently
                        # swallowed by this same except, cascading one column's failure
                        # into all the others. SQLite has no such abort state, which is
                        # why this only shows up once Postgres is the target.
                        conn.rollback()
        for index_ddl in (
            "CREATE INDEX IF NOT EXISTS ix_articles_is_starred ON articles (is_starred)",
            "CREATE INDEX IF NOT EXISTS ix_feeds_group_id ON feeds (group_id)",
            "CREATE INDEX IF NOT EXISTS ix_topics_group_id ON topics (group_id)",
            *(_VECTOR_INDEXES if vector_support["available"] and not _is_sqlite else ()),
        ):
            try:
                conn.execute(text(index_ddl))
                conn.commit()
            except Exception:
                conn.rollback()

    try:
        create_chat_views(engine)
    except Exception:
        # The Asistan's SQL tool then reports the error; the rest of the app must still start.
        import logging
        logging.getLogger(__name__).exception("Could not create the Asistan SQL views / read-only role")
