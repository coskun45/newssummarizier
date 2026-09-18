"""
Database connection and session management.
"""
from datetime import timezone
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator, DateTime as _DateTime
from app.core.config import settings

_is_sqlite = "sqlite" in settings.database_url

# Create database engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {}
)

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
