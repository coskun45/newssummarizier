"""
Group endpoints — the groups that RSS feeds and topics are listed under in the sidebar.
"""
from datetime import datetime
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db import crud, models
from app.db.database import get_db

router = APIRouter()

GroupKind = Literal["feed", "topic"]

# Members without a group are shown under this virtual group; a real group can't take its name.
OTHER_GROUP_NAME = "Diğer"
DUPLICATE_DETAIL = "Group with this name already exists"


def _clean_name(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ValueError("Grup adı boş olamaz")
    if crud.group_name_key(value) == crud.group_name_key(OTHER_GROUP_NAME):
        raise ValueError(f'"{OTHER_GROUP_NAME}" adı ayrılmıştır')
    return value


class GroupCreate(BaseModel):
    """Group creation request."""
    kind: GroupKind
    name: str = Field(max_length=100)
    display_order: int = Field(0, ge=0, le=10000)

    _check_name = field_validator("name")(_clean_name)


class GroupUpdate(BaseModel):
    """Group update request. Only provided fields are changed; `kind` is fixed."""
    name: Optional[str] = Field(None, max_length=100)
    display_order: Optional[int] = Field(None, ge=0, le=10000)

    _check_name = field_validator("name")(_clean_name)


class GroupResponse(BaseModel):
    """Group response model."""
    id: int
    kind: str
    name: str
    display_order: int
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/", response_model=List[GroupResponse])
def list_groups(kind: GroupKind = Query(...), db: Session = Depends(get_db)):
    """List the groups of one kind, in display order."""
    return crud.get_groups(db, kind)


@router.post("/", response_model=GroupResponse)
def create_group(
    group: GroupCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Create a group (admin only)."""
    try:
        return crud.create_group(db, kind=group.kind, name=group.name, display_order=group.display_order)
    except crud.DuplicateGroupName:
        raise HTTPException(status_code=400, detail=DUPLICATE_DETAIL)


@router.put("/{group_id}", response_model=GroupResponse)
def update_group(
    group_id: int,
    group_update: GroupUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Rename / reorder a group (admin only)."""
    try:
        group = crud.update_group(
            db, group_id, name=group_update.name, display_order=group_update.display_order
        )
    except crud.DuplicateGroupName:
        raise HTTPException(status_code=400, detail=DUPLICATE_DETAIL)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@router.delete("/{group_id}")
def delete_group(
    group_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete a group (admin only). Its members move to "Diğer"."""
    if not crud.delete_group(db, group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    return {"status": "deleted", "group_id": group_id}
