"""
API dependencies and shared utilities.
"""
from fastapi import Depends
from sqlalchemy.orm import Session
from app.db.database import get_db


def get_database() -> Session:
    """Get database session dependency."""
    return Depends(get_db)
