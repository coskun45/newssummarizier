"""
API routes for system prompts management.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from app.api.deps import get_db
from app.db import crud

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


class SystemPromptResponse(SystemPromptBase):
    """Schema for system prompt response."""
    id: int
    created_at: str
    updated_at: str
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[SystemPromptResponse])
async def get_system_prompts(db: Session = Depends(get_db)):
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


@router.get("/{prompt_type}", response_model=SystemPromptResponse)
async def get_system_prompt(prompt_type: str, db: Session = Depends(get_db)):
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
async def create_system_prompt(
    prompt: SystemPromptCreate,
    db: Session = Depends(get_db)
):
    """
    Create or update a system prompt.
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
async def update_system_prompt(
    prompt_type: str,
    prompt_update: SystemPromptUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an existing system prompt.
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
