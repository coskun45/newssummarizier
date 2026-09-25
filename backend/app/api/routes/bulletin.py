"""
Bulletin report endpoints: user-editable top-level categories (CRUD) and
on-demand Word (.docx) report generation.
"""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
def list_bulletin_categories(db: Session = Depends(get_db)):
    """List the user-defined top-level bulletin categories, in display order."""
    return crud.get_bulletin_categories(db)


@router.post("/categories", response_model=BulletinCategoryResponse)
def create_bulletin_category(
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
def reorder_bulletin_categories(
    body: BulletinCategoryReorderRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Reorder the top-level bulletin categories (admin only)."""
    return crud.reorder_bulletin_categories(db, body.ordered_ids)


@router.put("/categories/{category_id}", response_model=BulletinCategoryResponse)
def update_bulletin_category(
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
def delete_bulletin_category(
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


def _validate_priorities(priorities: Optional[List[str]]) -> None:
    if priorities:
        invalid = set(priorities) - VALID_PRIORITIES
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid priorities: {', '.join(sorted(invalid))}")


def _resolve_bulletin_date_range(
    published_from: Optional[datetime], published_to: Optional[datetime]
):
    """Shared 'default to the last 24h if unset' logic so /generate and
    /preview-count always agree on what 'no date filter' means."""
    to_ = published_to or datetime.now(timezone.utc)
    from_ = published_from or (to_ - timedelta(hours=24))
    return from_, to_


def _parse_comma_priorities(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [p for p in raw.split(",") if p]


class BulletinGenerateRequest(BaseModel):
    """Request body for generating a bulletin report."""
    published_from: Optional[datetime] = None
    published_to: Optional[datetime] = None
    priorities: Optional[List[str]] = None
    include_favorites: bool = False


class BulletinPreviewCountResponse(BaseModel):
    """Response body for the live, informational article-count preview."""
    count: int


@router.get("/preview-count", response_model=BulletinPreviewCountResponse)
def preview_bulletin_count(
    published_from: Optional[datetime] = None,
    published_to: Optional[datetime] = None,
    priorities: Optional[str] = None,
    include_favorites: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Live, read-only count of articles a bulletin would include for the given
    filters. Purely informational — does not require categories to exist and
    returns 0 (not a 400) when nothing matches, unlike /generate."""
    priority_list = _parse_comma_priorities(priorities)
    _validate_priorities(priority_list)
    from_, to_ = _resolve_bulletin_date_range(published_from, published_to)

    count = crud.count_bulletin_candidate_articles(
        db,
        start_date=from_,
        end_date=to_,
        priorities=priority_list,
        include_favorites=include_favorites,
    )
    return BulletinPreviewCountResponse(count=count)


@router.post("/generate")
async def generate_bulletin(
    body: BulletinGenerateRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Generate and stream back a Word (.docx) bulletin report for the given
    filters. Top-level categories come from the server's saved list, not the
    request, so the UI and the generated document can't drift apart."""
    _validate_priorities(body.priorities)

    categories = crud.get_bulletin_categories(db)
    if not categories:
        raise HTTPException(status_code=400, detail="En az bir üst düzey kategori tanımlanmalı")

    published_from, published_to = _resolve_bulletin_date_range(body.published_from, body.published_to)

    articles = crud.get_bulletin_candidate_articles(
        db,
        start_date=published_from,
        end_date=published_to,
        priorities=body.priorities,
        include_favorites=body.include_favorites,
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
    # A timestamped stored filename avoids collisions between multiple
    # reports generated on the same day; the friendly `filename` above is
    # what's actually shown/downloaded as.
    generated_at = datetime.now(timezone.utc)
    stored_filename = f"bulten-{generated_at.strftime('%Y%m%d-%H%M%S')}.docx"
    stored_path = bulletin_service.save_bulletin_file(buffer, stored_filename)
    crud.create_generated_bulletin(
        db,
        filename=filename,
        stored_path=stored_path,
        published_from=published_from,
        published_to=published_to,
        priorities=",".join(body.priorities) if body.priorities else None,
        include_favorites=body.include_favorites,
        article_count=len(articles),
    )

    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class GeneratedBulletinResponse(BaseModel):
    """A previously generated bulletin report, for the "past reports" list."""
    id: int
    filename: str
    published_from: Optional[datetime]
    published_to: Optional[datetime]
    priorities: Optional[List[str]]
    include_favorites: bool
    article_count: int
    generated_at: datetime


def _to_generated_bulletin_response(row: models.GeneratedBulletin) -> GeneratedBulletinResponse:
    return GeneratedBulletinResponse(
        id=row.id,
        filename=row.filename,
        published_from=row.published_from,
        published_to=row.published_to,
        priorities=row.priorities.split(",") if row.priorities else None,
        include_favorites=row.include_favorites,
        article_count=row.article_count,
        generated_at=row.generated_at,
    )


@router.get("/generated", response_model=List[GeneratedBulletinResponse])
def list_generated_bulletins(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Previously generated bulletin reports, newest first."""
    return [_to_generated_bulletin_response(row) for row in crud.get_generated_bulletins(db)]


@router.get("/generated/{bulletin_id}/download")
def download_generated_bulletin(
    bulletin_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Re-download a previously generated bulletin report."""
    row = crud.get_generated_bulletin(db, bulletin_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bülten bulunamadı")

    path = Path(row.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Bülten dosyası bulunamadı")

    return StreamingResponse(
        io.BytesIO(path.read_bytes()),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )


@router.delete("/generated/{bulletin_id}")
def delete_generated_bulletin(
    bulletin_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Delete a previously generated bulletin report (DB record and file). Admin only: reports are
    shared by all users."""
    row = crud.get_generated_bulletin(db, bulletin_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bülten bulunamadı")
    bulletin_service.delete_bulletin_file(row.stored_path)
    crud.delete_generated_bulletin(db, bulletin_id)
    return {"status": "success"}
