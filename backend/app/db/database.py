"""
Database connection and session management.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
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
        ("is_read", "BOOLEAN NOT NULL DEFAULT 0"),
        ("is_starred", "BOOLEAN NOT NULL DEFAULT 0"),
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
                        pass
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_articles_is_starred ON articles (is_starred)"))
                conn.commit()
            except Exception:
                pass
