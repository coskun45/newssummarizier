"""
Settings endpoints — global pipeline settings. Readable by every signed-in user; only admins can
change them, since they steer the pipeline (and its OpenAI cost) for everyone.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, field_validator
from app.db.database import get_db
from app.db import crud, models
from app.api.deps import require_admin
from app.core.config import settings as app_settings
from app.services.summary_service import (
    SELECTABLE_MODELS,
    SUMMARY_TYPES,
    available_models,
    get_enabled_summary_types,
    saved_model,
)
from app.tasks import scheduler
from app.agents.analysis.tools import (
    get_chat_require_plan_approval,
    get_enabled_chat_tools,
    normalize_enabled_tools,
)

router = APIRouter()

MIN_REFRESH_INTERVAL = 5 * 60  # seconds
MAX_REFRESH_INTERVAL = 24 * 3600
MAX_ARTICLE_AGE_HOURS = 365 * 24  # 0 = no limit


class UserSettings(BaseModel):
    """Settings update request. Partial: a field left out (None) keeps its stored value, so each
    Ayarlar tab saves only its own fields and never an unsaved edit from another tab."""
    enabled_topics: Optional[str] = None  # Comma-separated topic IDs. Empty = all topics
    enabled_summary_types: Optional[str] = None  # Comma-separated, at least one of SUMMARY_TYPES
    feed_refresh_interval: Optional[int] = Field(None, ge=MIN_REFRESH_INTERVAL, le=MAX_REFRESH_INTERVAL)  # seconds
    max_article_age_hours: Optional[int] = Field(None, ge=0, le=MAX_ARTICLE_AGE_HOURS)  # 0 = no limit
    # One of SELECTABLE_MODELS; "" clears the choice (back to DEFAULT_MODEL / DETAILED_MODEL).
    classification_model: Optional[str] = None
    summary_model: Optional[str] = None  # used by every summary type
    # Asistan: comma-separated tool names given to the model; at least one data tool stays on.
    chat_enabled_tools: Optional[str] = None
    chat_require_plan_approval: Optional[bool] = None  # wait for "Başlat" before running a plan

    @field_validator("enabled_topics")
    @classmethod
    def _topic_ids(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        parts = [p.strip() for p in value.split(",") if p.strip()]
        if not all(p.isdigit() for p in parts):
            raise ValueError("enabled_topics virgülle ayrılmış kategori id'leri olmalı")
        return ",".join(parts)

    @field_validator("enabled_summary_types")
    @classmethod
    def _summary_types(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        requested = {p.strip() for p in value.split(",") if p.strip()}
        unknown = requested - set(SUMMARY_TYPES)
        if unknown:
            raise ValueError(f"Bilinmeyen özet türü: {', '.join(sorted(unknown))}")
        if not requested:
            raise ValueError("En az bir özet türü seçilmelidir")
        return ",".join(t for t in SUMMARY_TYPES if t in requested)

    @field_validator("chat_enabled_tools")
    @classmethod
    def _chat_tools(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else normalize_enabled_tools(value)

    @field_validator("classification_model", "summary_model")
    @classmethod
    def _model(cls, value: Optional[str]) -> Optional[str]:
        if value not in (None, "") and value not in SELECTABLE_MODELS:
            raise ValueError(f"Bilinmeyen model: {value}")
        return value


class ModelOption(BaseModel):
    """A selectable OpenAI model and its list price (USD per 1M tokens)."""
    id: str
    input_per_1m: float
    output_per_1m: float


class DefaultModels(BaseModel):
    """The env models (DEFAULT_MODEL / DETAILED_MODEL) used while nothing is chosen in Ayarlar."""
    classification: str
    summary: str  # brief + standard
    detailed_summary: str


class SettingsResponse(BaseModel):
    """Settings response model."""
    enabled_topics: str
    enabled_summary_types: str
    feed_refresh_interval: int
    max_article_age_hours: int  # RSS entries older than this are skipped; 0 = no limit
    # The choice saved in Ayarlar; None = not chosen yet, `default_models` apply.
    classification_model: Optional[str]
    summary_model: Optional[str]
    default_models: DefaultModels
    available_models: List[ModelOption]
    chat_enabled_tools: str  # the tools the Asistan uses now (enabled and available)
    chat_require_plan_approval: bool


def _current_settings(db: Session) -> SettingsResponse:
    return SettingsResponse(
        enabled_topics=crud.get_setting(db, "enabled_topics") or "",
        enabled_summary_types=",".join(get_enabled_summary_types(db)),
        feed_refresh_interval=crud.get_feed_refresh_interval(db),
        max_article_age_hours=crud.get_max_article_age_hours(db),
        classification_model=saved_model(db, "classification_model"),
        summary_model=saved_model(db, "summary_model"),
        default_models=DefaultModels(
            classification=app_settings.default_model,
            summary=app_settings.default_model,
            detailed_summary=app_settings.detailed_model,
        ),
        available_models=available_models(),
        chat_enabled_tools=",".join(get_enabled_chat_tools(db)),
        chat_require_plan_approval=get_chat_require_plan_approval(db),
    )


@router.get("/", response_model=SettingsResponse)
def get_settings(db: Session = Depends(get_db)):
    """
    Get the pipeline settings.
    """
    return _current_settings(db)


@router.put("/", response_model=SettingsResponse)
def update_settings(
    update: UserSettings,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Update the pipeline settings (admin only). Only the fields sent are changed. A new refresh
    interval applies to the running scheduler right away.
    """
    interval = update.feed_refresh_interval
    # Rescheduling restarts the countdown (next run = now + interval), so only do it when the
    # interval really changed — saving other settings must not postpone the next refresh.
    interval_changed = interval is not None and interval != crud.get_feed_refresh_interval(db)
    if interval is not None:
        crud.set_setting(db, "feed_refresh_interval", str(interval))
    if update.max_article_age_hours is not None:
        crud.set_setting(db, "max_article_age_hours", str(update.max_article_age_hours))
    for key in ("enabled_topics", "enabled_summary_types", "classification_model", "summary_model"):
        value = getattr(update, key)
        if value is not None:
            crud.set_setting(db, key, value)
    if update.chat_require_plan_approval is not None:
        crud.set_setting(db, "chat_require_plan_approval", "true" if update.chat_require_plan_approval else "false")
    if update.chat_enabled_tools is not None:
        crud.set_setting(db, "chat_enabled_tools", update.chat_enabled_tools)
    if interval_changed:
        scheduler.reschedule_feed_processing(interval)

    return _current_settings(db)
