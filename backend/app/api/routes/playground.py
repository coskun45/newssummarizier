"""
Playground: inspect the current pipeline settings and dry-run the pipeline on a single stored
article with optional prompt overrides. Nothing is persisted.
"""
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import CostLimitExceededError
from app.api.deps import require_admin
from app.db import crud, models
from app.db.database import get_db
from app.services import summary_service

router = APIRouter()

STAGES = ("classification", "summarization")
MAX_PROMPT_CHARS = 20000


class PromptInfo(BaseModel):
    text: str
    source: str  # "db" | "default"


class SummaryTypeInfo(BaseModel):
    type: str
    model: str
    max_tokens: int
    default_instructions: str
    enabled: bool


class TopicInfo(BaseModel):
    name: str
    description: Optional[str] = None


class SummarizationLockedInfo(BaseModel):
    heading: str
    language_line: str


class PlaygroundSettingsResponse(BaseModel):
    classification_model: str
    classification_prompt: PromptInfo
    # Read-only part of the classification system message (live topic list + output format).
    classification_locked_text: str
    summarization_prompt: PromptInfo
    # Pieces of the read-only summarization block; the client joins them with the selected types.
    summarization_locked: SummarizationLockedInfo
    summary_types: List[SummaryTypeInfo]
    topics: List[TopicInfo]


class PlaygroundRunRequest(BaseModel):
    article_id: int
    stages: List[str] = Field(default_factory=lambda: list(STAGES))
    classification_prompt: Optional[str] = Field(default=None, max_length=MAX_PROMPT_CHARS)
    summarization_prompt: Optional[str] = Field(default=None, max_length=MAX_PROMPT_CHARS)
    summary_instructions: Optional[Dict[str, str]] = None
    summary_types: Optional[List[str]] = None
    force_summarize: bool = False


class Attempt(BaseModel):
    attempt: int
    user_prompt: str
    raw_response: Optional[str] = None
    error: Optional[str] = None
    input_tokens: int
    output_tokens: int
    finish_reason: Optional[str] = None
    latency_ms: int


class StageCall(BaseModel):
    model: str
    system_prompt: str
    prompt_source: str  # "override" | "db" | "default"
    temperature: float
    max_completion_tokens: int
    attempts: List[Attempt]
    error: Optional[str] = None
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int


class TopicResult(BaseModel):
    name: str
    confidence: Optional[float] = None
    known: bool  # exists in the topics table (unknown names are dropped by the real pipeline)


class ClassificationResult(StageCall):
    importance: Optional[str] = None
    priority: Optional[str] = None
    topics: List[TopicResult]
    pipeline_outcome: str  # "continue" | "filtered" | "failed"


class SummaryResult(StageCall):
    summary_type: str
    instructions: str
    summary_text: Optional[str] = None
    author: Optional[str] = None  # the person the model named in the header (None: no author)
    tokens_used: int


class ContentUsed(BaseModel):
    source: str  # "cleaned" | "raw" | "none"
    chars: int
    used_chars: int
    truncated: bool


class PlaygroundArticle(BaseModel):
    id: int
    title: str
    url: str


class PlaygroundRunResponse(BaseModel):
    article: PlaygroundArticle
    content_used: ContentUsed
    classification: Optional[ClassificationResult] = None
    summaries: List[SummaryResult]
    skipped_reason: Optional[str] = None  # "unimportant" | "classification_failed"
    total_cost: float


@router.get("/settings", response_model=PlaygroundSettingsResponse)
def get_playground_settings(db: Session = Depends(get_db)):
    """Model + prompt settings exactly as the pipeline would use them right now."""
    return summary_service.get_pipeline_settings(db)


@router.post("/run", response_model=PlaygroundRunResponse)
async def run_playground(
    body: PlaygroundRunRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Dry-run classification and/or summarization on one stored article. Persists nothing, but
    spends OpenAI budget — admin only."""
    invalid_stages = sorted(set(body.stages) - set(STAGES))
    if invalid_stages or not body.stages:
        raise HTTPException(status_code=400, detail=f"Invalid stages: {', '.join(invalid_stages) or '(none)'}")

    known_types = set(summary_service.SUMMARY_TYPES)
    invalid_types = sorted((set(body.summary_types or []) | set(body.summary_instructions or {})) - known_types)
    if invalid_types:
        raise HTTPException(status_code=400, detail=f"Invalid summary types: {', '.join(invalid_types)}")

    article = crud.get_article(db, body.article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    if "summarization" in body.stages and not (article.cleaned_content or article.raw_content):
        raise HTTPException(status_code=400, detail="Article has no content to summarize")

    try:
        result = await summary_service.run_playground(
            db,
            article,
            stages=body.stages,
            classification_prompt=body.classification_prompt,
            summarization_prompt=body.summarization_prompt,
            summary_instructions=body.summary_instructions,
            summary_types=body.summary_types,
            force_summarize=body.force_summarize,
        )
    except CostLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))

    return {"article": {"id": article.id, "title": article.title, "url": article.url}, **result}
