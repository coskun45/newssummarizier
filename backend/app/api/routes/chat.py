"""
Asistan (analysis chat) endpoints. Every user has their own conversations; another user's
conversation is "not found". Sending a message streams the agent's run as Server-Sent Events.
Also the vector-search status and the (admin) embedding backfill.
"""
import json
import time
from collections import defaultdict, deque
from datetime import datetime
from threading import Lock
from typing import Any, Deque, Dict, List, Literal, Optional

from anyio import from_thread
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings as app_settings
from app.db import crud, models
from app.db.database import get_db, vector_support
from app.agents.analysis.tools import tool_catalog
from app.services import chat_service

router = APIRouter()

DEFAULT_TITLE = "Yeni sohbet"
TITLE_LENGTH = 60
MAX_RUNS_PER_WINDOW = 10  # analysis runs a user may start per window (each costs OpenAI calls)
RUN_WINDOW_SECONDS = 60

_run_times: Dict[int, Deque[float]] = defaultdict(deque)
_run_lock = Lock()


def _allow_run(user_id: int) -> bool:
    now = time.monotonic()
    with _run_lock:
        times = _run_times[user_id]
        while times and now - times[0] > RUN_WINDOW_SECONDS:
            times.popleft()
        if len(times) >= MAX_RUNS_PER_WINDOW:
            return False
        times.append(now)
        return True


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)


class ConversationSummary(BaseModel):
    id: int
    title: str
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    events: List[Dict[str, Any]]
    cost: float
    created_at: Optional[datetime] = None


class ConversationDetail(ConversationSummary):
    messages: List[MessageOut]
    pending: Optional[Dict[str, Any]] = None  # clarifying questions / plan awaiting approval


class MessageCreate(BaseModel):
    content: str = Field("", max_length=4000)
    # "approve_plan" with empty content starts the waiting plan; with content it revises it.
    action: Literal["message", "approve_plan"] = "message"


class ToolInfo(BaseModel):
    name: str
    label: str
    description: str
    data_tool: bool
    available: bool
    unavailable_reason: Optional[str] = None
    enabled: bool
    active: bool


def _own_conversation(db: Session, conversation_id: int, user: models.User) -> models.ChatConversation:
    conversation = crud.get_chat_conversation(db, conversation_id, user_id=user.id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Sohbet bulunamadı")
    return conversation


def _message_out(message: models.ChatMessage) -> MessageOut:
    try:
        events = json.loads(message.events) if message.events else []
    except ValueError:
        events = []
    return MessageOut(id=message.id, role=message.role, content=message.content, events=events,
                      cost=message.cost or 0.0, created_at=message.created_at)


def _detail(conversation: models.ChatConversation) -> ConversationDetail:
    return ConversationDetail(
        id=conversation.id, title=conversation.title, status=conversation.status,
        created_at=conversation.created_at, updated_at=conversation.updated_at,
        messages=[_message_out(m) for m in conversation.messages],
        pending=chat_service.pending_of(conversation),
    )


@router.get("/tools", response_model=List[ToolInfo])
def list_tools(db: Session = Depends(get_db)):
    """The Asistan's tools with availability and the Ayarlar on/off state."""
    return tool_catalog(db)


@router.get("/conversations", response_model=List[ConversationSummary])
def list_conversations(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    return crud.get_chat_conversations(db, current_user.id)


@router.post("/conversations", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    title = (body.title or "").strip() or DEFAULT_TITLE
    return _detail(crud.create_chat_conversation(db, current_user.id, title))


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _detail(_own_conversation(db, conversation_id, current_user))


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    conversation = _own_conversation(db, conversation_id, current_user)
    if conversation.status == "running":
        raise HTTPException(status_code=409, detail="Analiz sürerken sohbet silinemez")
    crud.delete_chat_conversation(db, conversation.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/conversations/{conversation_id}/messages")
def send_message(
    conversation_id: int,
    body: MessageCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Ask a question, answer a clarifying question, or start/revise a plan waiting for approval.
    Streams the agent's events (text/event-stream) and ends with a `done` event."""
    conversation = _own_conversation(db, conversation_id, current_user)
    content = body.content.strip()
    if body.action == "message" and not content:
        raise HTTPException(status_code=400, detail="Mesaj boş olamaz")
    if body.action == "approve_plan" and conversation.status != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail="Onay bekleyen bir plan yok")
    if not _allow_run(current_user.id):
        raise HTTPException(status_code=429, detail="Çok fazla analiz isteği; biraz sonra tekrar deneyin")

    first_message = not conversation.messages
    previous_status = crud.claim_chat_conversation(db, conversation.id)
    if previous_status is None:
        raise HTTPException(status_code=409, detail="Bu sohbette bir analiz zaten sürüyor")
    if first_message and conversation.title == DEFAULT_TITLE and content:
        crud.update_chat_conversation(db, conversation.id, title=content[:TITLE_LENGTH])
    user_text = content or "Planı başlat"
    crud.add_chat_message(db, conversation.id, "user", user_text)

    return StreamingResponse(
        chat_service.stream_turn(conversation.id, previous_status, content, body.action),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class EmbeddingJob(BaseModel):
    status: str  # idle | running | done
    total: int
    done: int
    failed: int
    cost: float
    error: Optional[str] = None


class EmbeddingStatus(BaseModel):
    available: bool  # pgvector is there
    unavailable_reason: Optional[str] = None
    model: str
    dimensions: int
    summarized: int  # summarized articles (what gets embedded)
    embedded: int  # of those, with a summary embedding of the current model
    chunks: int  # full-text chunk embeddings
    no_text: int  # summarized articles with no text at all (no page, no RSS text): never embeddable
    job: EmbeddingJob


def _embedding_status(db: Session) -> EmbeddingStatus:
    from app.tasks.background import get_embedding_backfill_status
    return EmbeddingStatus(
        available=vector_support["available"],
        unavailable_reason=vector_support["reason"],
        model=app_settings.embedding_model,
        dimensions=app_settings.embedding_dimensions,
        **crud.get_embedding_stats(db, app_settings.embedding_model),
        job=EmbeddingJob(**get_embedding_backfill_status()),
    )


@router.get("/embeddings/status", response_model=EmbeddingStatus)
def get_embedding_status(db: Session = Depends(get_db)):
    """How many summarized articles are vectorized, and the backfill job's progress."""
    return _embedding_status(db)


@router.post("/embeddings/backfill", response_model=EmbeddingStatus)
def start_embedding_backfill(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Vectorize every summarized article that isn't yet (admin only — it spends OpenAI budget).
    Runs in the background; poll GET /embeddings/status."""
    if not vector_support["available"]:
        raise HTTPException(status_code=409, detail=vector_support["reason"] or "Vektör veritabanı kullanılamıyor")
    from app.tasks.background import embed_missing_articles_task, register_embedding_backfill
    if not from_thread.run_sync(register_embedding_backfill):
        raise HTTPException(status_code=409, detail="Vektörleştirme zaten sürüyor")
    background_tasks.add_task(embed_missing_articles_task)
    return _embedding_status(db)
