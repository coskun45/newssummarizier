"""
API routes for system prompts management.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_db, require_admin
from app.db import crud, models
from app.services import summary_service

router = APIRouter()


class SystemPromptBase(BaseModel):
    """Base schema for system prompts."""
    prompt_type: str
    prompt_text: str
    is_active: bool = True


class SystemPromptCreate(SystemPromptBase):
    """Schema for creating system prompts."""
    pass


class SystemPromptUpdate(BaseModel):
    """Schema for updating system prompts."""
    prompt_text: Optional[str] = None
    is_active: Optional[bool] = None


class LockedPromptResponse(BaseModel):
    """Read-only part of a prompt that the pipeline appends itself (not editable, not stored)."""
    prompt_type: str
    locked_text: str


class SystemPromptResponse(SystemPromptBase):
    """Schema for system prompt response."""
    id: int
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[SystemPromptResponse])
def get_system_prompts(db: Session = Depends(get_db)):
    """
    Get all system prompts.
    """
    prompts = crud.get_all_system_prompts(db)
    
    # Convert datetime to ISO string
    result = []
    for prompt in prompts:
        result.append({
            "id": prompt.id,
            "prompt_type": prompt.prompt_type,
            "prompt_text": prompt.prompt_text,
            "is_active": prompt.is_active,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None
        })
    
    return result


@router.get("/{prompt_type}/locked", response_model=LockedPromptResponse)
def get_locked_prompt(prompt_type: str, db: Session = Depends(get_db)):
    """
    Get the locked (read-only) part the pipeline appends to a prompt, rendered with the live
    data — for `classification` the current topic list plus the JSON output format, for
    `summarization` the instructions of the enabled summary types plus the language line.
    Other prompt types have no locked part and return an empty string.
    """
    if prompt_type == "classification":
        locked_text = summary_service.build_classification_locked_text(crud.get_topics(db))
    elif prompt_type == "summarization":
        # Only the summary types enabled in Settings are generated, so only those are listed.
        locked_text = summary_service.build_summarization_locked_text(summary_service.get_enabled_summary_types(db))
    else:
        locked_text = ""
    return {"prompt_type": prompt_type, "locked_text": locked_text}


@router.get("/{prompt_type}", response_model=SystemPromptResponse)
def get_system_prompt(prompt_type: str, db: Session = Depends(get_db)):
    """
    Get a specific system prompt by type.
    """
    prompt = crud.get_system_prompt(db, prompt_type)
    if not prompt:
        raise HTTPException(status_code=404, detail=f"System prompt '{prompt_type}' not found")
    
    return {
        "id": prompt.id,
        "prompt_type": prompt.prompt_type,
        "prompt_text": prompt.prompt_text,
        "is_active": prompt.is_active,
        "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
        "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None
    }


@router.post("/", response_model=SystemPromptResponse)
def create_system_prompt(
    prompt: SystemPromptCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Create or update a system prompt (admin only).
    """
    db_prompt = crud.upsert_system_prompt(
        db,
        prompt_type=prompt.prompt_type,
        prompt_text=prompt.prompt_text,
        is_active=prompt.is_active
    )
    
    return {
        "id": db_prompt.id,
        "prompt_type": db_prompt.prompt_type,
        "prompt_text": db_prompt.prompt_text,
        "is_active": db_prompt.is_active,
        "created_at": db_prompt.created_at.isoformat() if db_prompt.created_at else None,
        "updated_at": db_prompt.updated_at.isoformat() if db_prompt.updated_at else None
    }


@router.put("/{prompt_type}", response_model=SystemPromptResponse)
def update_system_prompt(
    prompt_type: str,
    prompt_update: SystemPromptUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """
    Update an existing system prompt (admin only).
    """
    db_prompt = crud.update_system_prompt(
        db,
        prompt_type=prompt_type,
        prompt_text=prompt_update.prompt_text,
        is_active=prompt_update.is_active
    )
    
    if not db_prompt:
        raise HTTPException(status_code=404, detail=f"System prompt '{prompt_type}' not found")
    
    return {
        "id": db_prompt.id,
        "prompt_type": db_prompt.prompt_type,
        "prompt_text": db_prompt.prompt_text,
        "is_active": db_prompt.is_active,
        "created_at": db_prompt.created_at.isoformat() if db_prompt.created_at else None,
        "updated_at": db_prompt.updated_at.isoformat() if db_prompt.updated_at else None
    }
