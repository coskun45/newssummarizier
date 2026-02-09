"""
Settings endpoints.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from app.db.database import get_db
from app.db import crud
import json

router = APIRouter()


class UserSettings(BaseModel):
    """User settings model."""
    enabled_topics: str = ""  # Comma-separated topic IDs. Empty = all topics
    enabled_summary_types: str = "brief,standard,detailed"  # Comma-separated: brief, standard, detailed
    feed_refresh_interval: int = 1800  # seconds


class SettingsResponse(BaseModel):
    """Settings response model."""
    enabled_topics: str
    enabled_summary_types: str
    feed_refresh_interval: int


@router.get("/", response_model=SettingsResponse)
async def get_settings(db: Session = Depends(get_db)):
    """
    Get user settings.
    """
    # Get settings from database or use defaults
    enabled_topics = crud.get_setting(db, "enabled_topics") or ""
    enabled_summary_types = crud.get_setting(db, "enabled_summary_types") or "brief,standard,detailed"
    feed_refresh_interval = crud.get_setting(db, "feed_refresh_interval") or "1800"
    
    return SettingsResponse(
        enabled_topics=enabled_topics,
        enabled_summary_types=enabled_summary_types,
        feed_refresh_interval=int(feed_refresh_interval)
    )


@router.put("/", response_model=SettingsResponse)
async def update_settings(settings: UserSettings, db: Session = Depends(get_db)):
    """
    Update user settings.
    """
    # Save settings to database
    crud.set_setting(db, "enabled_topics", settings.enabled_topics)
    crud.set_setting(db, "enabled_summary_types", settings.enabled_summary_types)
    crud.set_setting(db, "feed_refresh_interval", str(settings.feed_refresh_interval))
    
    return SettingsResponse(
        enabled_topics=settings.enabled_topics,
        enabled_summary_types=settings.enabled_summary_types,
        feed_refresh_interval=settings.feed_refresh_interval
    )
