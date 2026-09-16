"""
Bulletin report endpoints: user-editable top-level categories (CRUD) and
on-demand Word (.docx) report generation.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.exceptions import BulletinGenerationError, CostLimitExceededError
from app.db import crud, models
from app.db.database import get_db
from app.services import bulletin_service

router = APIRouter()


class BulletinCategoryCreate(BaseModel):
    """Bulletin category creation model."""
    name: str


class BulletinCategoryUpdate(BaseModel):
    """Bulletin category update model."""
    name: Optional[str] = None


class BulletinCategoryResponse(BaseModel):
    """Bulletin category response model."""
    id: int
    name: str
    display_order: int

    class Config:
        from_attributes = True


class BulletinCategoryReorderRequest(BaseModel):
    """Request body for reordering bulletin categories."""
    ordered_ids: List[int]


@router.get("/categories", response_model=List[BulletinCategoryResponse])
async def list_bulletin_categories(db: Session = Depends(get_db)):
    """List the user-defined top-level bulletin categories, in display order."""
    return crud.get_bulletin_categories(db)


@router.post("/categories", response_model=BulletinCategoryResponse)
async def create_bulletin_category(
    body: BulletinCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Create a new top-level bulletin category (admin only)."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    if crud.get_bulletin_category_by_name(db, name):
        raise HTTPException(status_code=400, detail="A category with this name already exists")
    return crud.create_bulletin_category(db, name)


@router.put("/categories/reorder", response_model=List[BulletinCategoryResponse])
async def reorder_bulletin_categories(
    body: BulletinCategoryReorderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Reorder the top-level bulletin categories (admin only)."""
    return crud.reorder_bulletin_categories(db, body.ordered_ids)


@router.put("/categories/{category_id}", response_model=BulletinCategoryResponse)
async def update_bulletin_category(
    category_id: int,
    body: BulletinCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Rename a top-level bulletin category (admin only)."""
    existing = crud.get_bulletin_category(db, category_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Category not found")

    name = body.name.strip() if body.name else None
    if name:
        name_taken = crud.get_bulletin_category_by_name(db, name)
        if name_taken and name_taken.id != category_id:
            raise HTTPException(status_code=400, detail="A category with this name already exists")

    return crud.update_bulletin_category(db, category_id, name=name)


@router.delete("/categories/{category_id}")
async def delete_bulletin_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete a top-level bulletin category (admin only)."""
    if not crud.get_bulletin_category(db, category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    crud.delete_bulletin_category(db, category_id)
    return {"status": "success"}


VALID_PRIORITIES = {"high", "med", "low"}


class BulletinGenerateRequest(BaseModel):
    """Request body for generating a bulletin report."""
    published_from: Optional[datetime] = None
    published_to: Optional[datetime] = None
    priorities: Optional[List[str]] = None


@router.post("/generate")
async def generate_bulletin(
    body: BulletinGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate and stream back a Word (.docx) bulletin report for the given
    filters. Top-level categories come from the server's saved list, not the
    request, so the UI and the generated document can't drift apart."""
    if body.priorities:
        invalid = set(body.priorities) - VALID_PRIORITIES
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid priorities: {', '.join(sorted(invalid))}")

    categories = crud.get_bulletin_categories(db)
    if not categories:
        raise HTTPException(status_code=400, detail="En az bir üst düzey kategori tanımlanmalı")

    published_to = body.published_to or datetime.now(timezone.utc)
    published_from = body.published_from or (published_to - timedelta(hours=24))

    articles = crud.get_articles(
        db,
        start_date=published_from,
        end_date=published_to,
        priorities=body.priorities,
        limit=settings.bulletin_max_articles + 1,
    )
    if len(articles) > settings.bulletin_max_articles:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Seçilen aralıkta çok fazla haber var ({len(articles)}). "
                "Tarih aralığını veya önem seviyesi filtresini daraltın."
            ),
        )
    if not articles:
        raise HTTPException(status_code=400, detail="Seçilen aralıkta haber bulunamadı")

    try:
        buffer = await bulletin_service.generate_bulletin_report(db, articles, categories)
    except CostLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except BulletinGenerationError as e:
        raise HTTPException(status_code=500, detail=str(e))

    filename = f"bulten-{published_to.date().isoformat()}.docx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
