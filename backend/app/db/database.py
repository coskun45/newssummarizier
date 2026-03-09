"""
Database connection and session management.
"""
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import settings

# Create database engine
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

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
    """Initialize database tables."""
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    # Add new columns to existing DB if they don't exist (SQLite doesn't support IF NOT EXISTS for columns)
    with engine.connect() as conn:
        for col, coltype in [("importance", "VARCHAR"), ("priority", "VARCHAR")]:
            try:
                conn.execute(text(f"ALTER TABLE articles ADD COLUMN {col} {coltype}"))
                conn.commit()
            except Exception:
                pass
