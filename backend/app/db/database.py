"""
Database connection and session management.
"""
from datetime import timezone
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator, DateTime as _DateTime
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


def init_db():
    """Create tables and apply lightweight, idempotent column migrations.

    SQLAlchemy's create_all() creates missing tables but never alters existing
    ones. So when a new column is added to a model, we also add it here for
    databases created before the change — runs on every startup, no separate
    migrate_*.py scripts needed. Fresh databases already get every column from
    create_all(), so the loop simply finds nothing to do.
    """
    from sqlalchemy import text, inspect
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

    inspector = inspect(engine)
    if inspector.has_table("articles"):
        existing = {c["name"] for c in inspector.get_columns("articles")}
        with engine.connect() as conn:
            for column, ddl in article_columns:
                if column not in existing:
                    try:
                        conn.execute(text(f"ALTER TABLE articles ADD COLUMN {column} {ddl}"))
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
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_articles_is_starred ON articles (is_starred)"))
                conn.commit()
            except Exception:
                conn.rollback()
