"""
Summary and topic endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime
from app.db.database import get_db
from app.db import crud

router = APIRouter()


class SummaryResponse(BaseModel):
    """Summary response model."""
    id: int
    article_id: int
    summary_text: str
    summary_type: str
    model_used: str
    tokens_used: int
    cost: float
    created_at: datetime
    
    class Config:
        from_attributes = True


class CostStatsResponse(BaseModel):
    """Cost statistics response."""
    daily_cost: float
    monthly_cost: float
    daily_limit: float
    monthly_limit: float


@router.get("/articles/{article_id}/summaries", response_model=List[SummaryResponse])
async def get_article_summaries(
    article_id: int,
    summary_type: str = Query(None, description="Filter by summary type: brief, standard, detailed"),
    db: Session = Depends(get_db)
):
    """
    Get all summaries for an article.
    """
    # Check if article exists
    article = crud.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Get summaries
    summaries = crud.get_summaries_by_article(db, article_id, summary_type)
    
    return summaries


@router.get("/articles/{article_id}/summary/{summary_type}", response_model=SummaryResponse)
async def get_article_summary_by_type(
    article_id: int,
    summary_type: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific summary type for an article.
    """
    # Validate summary type
    if summary_type not in ["brief", "standard", "detailed"]:
        raise HTTPException(status_code=400, detail="Invalid summary type")
    
    # Check if article exists
    article = crud.get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Get summary
    summaries = crud.get_summaries_by_article(db, article_id, summary_type)
    if not summaries:
        raise HTTPException(status_code=404, detail=f"No {summary_type} summary found for this article")
    
    # Return most recent summary of this type
    return summaries[-1]


@router.get("/stats/costs", response_model=CostStatsResponse)
async def get_cost_stats(db: Session = Depends(get_db)):
    """
    Get API cost statistics.
    """
    from app.core.config import settings
    
    daily_cost = crud.get_daily_cost(db)
    monthly_cost = crud.get_monthly_cost(db)
    
    return CostStatsResponse(
        daily_cost=daily_cost,
        monthly_cost=monthly_cost,
        daily_limit=settings.daily_cost_limit,
        monthly_limit=settings.monthly_cost_limit
    )
