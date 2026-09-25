"""
Settings endpoints — global pipeline settings. Readable by every signed-in user; only admins can
change them, since they steer the pipeline (and its OpenAI cost) for everyone.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from app.db.database import get_db
from app.db import crud, models
from app.api.deps import require_admin
from app.services.summary_service import SUMMARY_TYPES, get_enabled_summary_types
from app.tasks import scheduler

router = APIRouter()

MIN_REFRESH_INTERVAL = 5 * 60  # seconds
MAX_REFRESH_INTERVAL = 24 * 3600


class UserSettings(BaseModel):
    """Settings update request."""
    enabled_topics: str = ""  # Comma-separated topic IDs. Empty = all topics
    enabled_summary_types: str = ",".join(SUMMARY_TYPES)  # Comma-separated, at least one of SUMMARY_TYPES
    feed_refresh_interval: int = Field(3600, ge=MIN_REFRESH_INTERVAL, le=MAX_REFRESH_INTERVAL)  # seconds

    @field_validator("enabled_topics")
    @classmethod
    def _topic_ids(cls, value: str) -> str:
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not all(p.isdigit() for p in parts):
            raise ValueError("enabled_topics virgülle ayrılmış kategori id'leri olmalı")
        return ",".join(parts)

    @field_validator("enabled_summary_types")
    @classmethod
    def _summary_types(cls, value: str) -> str:
        requested = {p.strip() for p in value.split(",") if p.strip()}
        unknown = requested - set(SUMMARY_TYPES)
        if unknown:
            raise ValueError(f"Bilinmeyen özet türü: {', '.join(sorted(unknown))}")
        if not requested:
            raise ValueError("En az bir özet türü seçilmelidir")
        return ",".join(t for t in SUMMARY_TYPES if t in requested)


class SettingsResponse(BaseModel):
    """Settings response model."""
    enabled_topics: str
    enabled_summary_types: str
    feed_refresh_interval: int


def _current_settings(db: Session) -> SettingsResponse:
    return SettingsResponse(
        enabled_topics=crud.get_setting(db, "enabled_topics") or "",
        enabled_summary_types=",".join(get_enabled_summary_types(db)),
        feed_refresh_interval=crud.get_feed_refresh_interval(db),
    )


@router.get("/", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    """
    Get the pipeline settings.
    """
    return _current_settings(db)


@router.put("/", response_model=SettingsResponse)
def update_settings(
    settings: UserSettings,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Update the pipeline settings (admin only). A new refresh interval applies to the running
    scheduler right away.
    """
    interval_changed = settings.feed_refresh_interval != crud.get_feed_refresh_interval(db)
    crud.set_setting(db, "enabled_topics", settings.enabled_topics)
    crud.set_setting(db, "enabled_summary_types", settings.enabled_summary_types)
    crud.set_setting(db, "feed_refresh_interval", str(settings.feed_refresh_interval))
    # Rescheduling restarts the countdown (next run = now + interval), so only do it when the
    # interval really changed — saving other settings must not postpone the next refresh.
    if interval_changed:
        scheduler.reschedule_feed_processing(settings.feed_refresh_interval)

    return _current_settings(db)
