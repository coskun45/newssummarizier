"""
Bulletin subscription endpoints.

`router` (JWT, mounted at /api/newsletter): a user manages their own subscriptions; admins see and
manage everyone's. `public_router` (no JWT, /api/newsletter/public): the confirm / unsubscribe
links in the mails. Those GET links only show a page with a button — the change itself is a POST,
because mail scanners (e.g. Outlook Safe Links) open every GET link in a mail on their own.
"""
import html
import re
from datetime import datetime, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.db import crud, models
from app.db.database import get_db
from app.services import email_service, newsletter_service

router = APIRouter()
public_router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]{2,}$")
_MAX_EMAIL_LENGTH = 254


# ==================== Schemas ====================

class SubscriptionBody(BaseModel):
    """Create / full update of a subscription."""
    email: str = Field(max_length=_MAX_EMAIL_LENGTH)
    frequency: Literal["daily", "weekly"]
    send_hour: int = Field(ge=0, le=23)
    send_weekday: Optional[int] = Field(None, ge=0, le=6)  # 0=Pazartesi; weekly only
    max_articles: int = Field(ge=1)
    priorities: List[Literal["high", "med", "low"]] = []  # empty = all
    include_favorites: bool = False
    category_ids: List[int] = []  # empty = all top-level categories
    delivery_format: Literal["docx", "email", "both"]


class SubscriptionResponse(BaseModel):
    id: int
    email: str
    owner_email: str
    frequency: str
    send_hour: int
    send_weekday: Optional[int]
    max_articles: int
    priorities: List[str]
    include_favorites: bool
    category_ids: List[int]
    delivery_format: str
    status: str
    consecutive_failures: int
    confirm_sent_at: Optional[datetime]
    last_sent_at: Optional[datetime]
    created_at: datetime


class DeliveryResponse(BaseModel):
    id: int
    sent_at: datetime
    status: str
    article_count: int
    attempts: int
    manual: bool
    cost: float
    error: Optional[str]

    class Config:
        from_attributes = True


class SendNowResponse(BaseModel):
    status: Literal["queued"]


class NewsletterStatusResponse(BaseModel):
    email_configured: bool
    max_articles_limit: int
    max_subscriptions: int
    timezone: str


class AdminSubscriptionsResponse(BaseModel):
    subscriptions: List[SubscriptionResponse]
    cost_last_30_days: float
    categories_missing: bool


def _to_response(sub: models.NewsletterSubscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        email=sub.email,
        owner_email=sub.user.email if sub.user else "",
        frequency=sub.frequency,
        send_hour=sub.send_hour,
        send_weekday=sub.send_weekday,
        max_articles=sub.max_articles,
        priorities=sub.priorities.split(",") if sub.priorities else [],
        include_favorites=sub.include_favorites,
        category_ids=sub.category_ids,
        delivery_format=sub.delivery_format,
        status=sub.status,
        consecutive_failures=sub.consecutive_failures or 0,
        confirm_sent_at=sub.confirm_sent_at,
        last_sent_at=sub.last_sent_at,
        created_at=sub.created_at,
    )


# ==================== Helpers ====================

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_own_email(email: str, user: models.User) -> bool:
    return crud.normalize_email(email) == crud.normalize_email(user.email)


def _validate_body(db: Session, body: SubscriptionBody) -> None:
    if not _EMAIL_RE.match(body.email.strip()):
        raise HTTPException(status_code=400, detail="Geçerli bir e-posta adresi girin")
    if body.frequency == "weekly" and body.send_weekday is None:
        raise HTTPException(status_code=400, detail="Haftalık bülten için gönderim günü seçilmeli")
    if body.max_articles > settings.bulletin_max_articles:
        raise HTTPException(
            status_code=400, detail=f"Haber sayısı en fazla {settings.bulletin_max_articles} olabilir"
        )
    known = {c.id for c in crud.get_bulletin_categories(db)}
    unknown = set(body.category_ids) - known
    if unknown:
        raise HTTPException(status_code=400, detail="Geçersiz kategori seçimi")


def _ensure_not_duplicate(db: Session, user_id: int, body: SubscriptionBody, exclude_id: Optional[int] = None) -> None:
    if crud.find_duplicate_newsletter_subscription(
        db, user_id, crud.newsletter_settings_key(body), exclude_id=exclude_id
    ):
        raise HTTPException(status_code=400, detail="Bu adres için aynı ayarlarla bir abonelik zaten var")


def _ensure_below_limit(db: Session, user_id: int) -> None:
    if crud.count_user_newsletter_subscriptions(db, user_id) >= newsletter_service.MAX_SUBSCRIPTIONS_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"En fazla {newsletter_service.MAX_SUBSCRIPTIONS_PER_USER} abonelik oluşturabilirsiniz",
        )


def _get_accessible(db: Session, subscription_id: int, user: models.User) -> models.NewsletterSubscription:
    """The subscription if it is the user's own (or the user is admin); 404 otherwise, so other
    users' subscription ids aren't even confirmed to exist."""
    sub = crud.get_newsletter_subscription(db, subscription_id)
    if not sub or (sub.user_id != user.id and user.role != "admin"):
        raise HTTPException(status_code=404, detail="Abonelik bulunamadı")
    return sub


def _ensure_confirmation_quota(user: models.User) -> None:
    if not newsletter_service.confirmation_quota_left(user.id):
        raise HTTPException(
            status_code=429,
            detail="Çok fazla onay maili gönderildi; lütfen bir saat sonra tekrar deneyin",
        )


async def _start_confirmation(db: Session, sub: models.NewsletterSubscription, user: models.User) -> None:
    crud.update_newsletter_subscription(
        db, sub, status="pending", confirm_token=newsletter_service.new_token(), confirm_sent_at=None
    )
    await newsletter_service.send_confirmation(db, sub, user)


# ==================== Protected routes ====================

@router.get("/status", response_model=NewsletterStatusResponse)
def newsletter_status():
    """Whether mail sending is set up, and the limits the form needs."""
    return NewsletterStatusResponse(
        email_configured=email_service.is_configured(),
        max_articles_limit=settings.bulletin_max_articles,
        max_subscriptions=newsletter_service.MAX_SUBSCRIPTIONS_PER_USER,
        timezone=settings.newsletter_timezone,
    )


@router.get("/subscriptions", response_model=List[SubscriptionResponse])
def list_my_subscriptions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """The current user's subscriptions, newest first."""
    return [_to_response(s) for s in crud.get_newsletter_subscriptions(db, user_id=current_user.id)]


@router.post("/subscriptions", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: SubscriptionBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a subscription. The user's own account address is active at once; any other address
    gets a confirmation mail and stays "pending" until the link in it is used."""
    _validate_body(db, body)
    _ensure_below_limit(db, current_user.id)
    _ensure_not_duplicate(db, current_user.id, body)

    own = _is_own_email(body.email, current_user)
    if not own:
        _ensure_confirmation_quota(current_user)
    sub = crud.create_newsletter_subscription(
        db,
        user_id=current_user.id,
        email=body.email,
        frequency=body.frequency,
        send_hour=body.send_hour,
        send_weekday=body.send_weekday,
        max_articles=body.max_articles,
        priorities=body.priorities,
        include_favorites=body.include_favorites,
        delivery_format=body.delivery_format,
        category_ids=body.category_ids,
        status="active" if own else "pending",
        unsubscribe_token=newsletter_service.new_token(),
        confirm_token=None if own else newsletter_service.new_token(),
        active_since=_now() if own else None,
    )
    if not own:
        await newsletter_service.send_confirmation(db, sub, current_user)
    return _to_response(sub)


@router.put("/subscriptions/{subscription_id}", response_model=SubscriptionResponse)
async def update_subscription(
    subscription_id: int,
    body: SubscriptionBody,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Replace a subscription's settings. A new address that isn't the owner's own needs a new
    confirmation; a schedule change doesn't back-fill the slot that just passed."""
    sub = _get_accessible(db, subscription_id, current_user)
    _validate_body(db, body)
    _ensure_not_duplicate(db, sub.user_id, body, exclude_id=sub.id)

    email_changed = crud.normalize_email(body.email) != sub.email
    if email_changed and not _is_own_email(body.email, sub.user):
        _ensure_confirmation_quota(current_user)
    schedule_changed = (body.frequency, body.send_hour, body.send_weekday if body.frequency == "weekly" else None) \
        != (sub.frequency, sub.send_hour, sub.send_weekday)
    fields = body.model_dump(exclude={"category_ids"})
    if schedule_changed:
        fields["active_since"] = _now()
    sub = crud.update_newsletter_subscription(db, sub, category_ids=body.category_ids, **fields)

    if email_changed:
        if _is_own_email(sub.email, sub.user):
            if sub.status == "pending":
                crud.update_newsletter_subscription(db, sub, status="active", confirm_token=None, active_since=_now())
        elif sub.status != "unsubscribed":
            await _start_confirmation(db, sub, current_user)
    return _to_response(sub)


@router.delete("/subscriptions/{subscription_id}")
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Delete a subscription and its delivery history (owner or admin)."""
    sub = _get_accessible(db, subscription_id, current_user)
    crud.delete_newsletter_subscription(db, sub.id)
    return {"status": "success"}


@router.post("/subscriptions/{subscription_id}/pause", response_model=SubscriptionResponse)
def pause_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sub = _get_accessible(db, subscription_id, current_user)
    if sub.status != "active":
        raise HTTPException(status_code=400, detail="Yalnızca aktif abonelik durdurulabilir")
    return _to_response(crud.update_newsletter_subscription(db, sub, status="paused"))


@router.post("/subscriptions/{subscription_id}/resume", response_model=SubscriptionResponse)
async def resume_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Paused/disabled → active again. A recipient who unsubscribed themselves is only
    re-subscribed after confirming again (unless it is the owner's own address)."""
    sub = _get_accessible(db, subscription_id, current_user)
    if sub.status not in ("paused", "disabled", "unsubscribed"):
        raise HTTPException(status_code=400, detail="Bu abonelik zaten aktif veya onay bekliyor")
    if sub.status == "unsubscribed":
        # Unsubscribed rows are outside the cap and the duplicate check, so re-check both here.
        _ensure_below_limit(db, sub.user_id)
        if crud.find_duplicate_newsletter_subscription(
            db, sub.user_id, crud.newsletter_settings_key(sub), exclude_id=sub.id
        ):
            raise HTTPException(status_code=400, detail="Bu adres için aynı ayarlarla bir abonelik zaten var")
    if sub.status == "unsubscribed" and not _is_own_email(sub.email, sub.user):
        _ensure_confirmation_quota(current_user)
        await _start_confirmation(db, sub, current_user)
        return _to_response(sub)
    return _to_response(crud.update_newsletter_subscription(
        db, sub, status="active", consecutive_failures=0, active_since=_now()
    ))


@router.post("/subscriptions/{subscription_id}/resend-confirmation", response_model=SubscriptionResponse)
async def resend_confirmation(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sub = _get_accessible(db, subscription_id, current_user)
    if sub.status != "pending":
        raise HTTPException(status_code=400, detail="Abonelik onay beklemiyor")
    if sub.confirm_sent_at and _now() - sub.confirm_sent_at < newsletter_service.CONFIRM_RESEND_COOLDOWN:
        raise HTTPException(status_code=429, detail="Onay maili en fazla saatte bir kez gönderilebilir")
    if not email_service.is_configured():
        raise HTTPException(status_code=400, detail="E-posta gönderimi yapılandırılmamış")
    _ensure_confirmation_quota(current_user)
    # Same token as before: if this send fails, the link already in the inbox keeps working;
    # if it succeeds, confirm_sent_at moves on and extends the link's validity.
    if not await newsletter_service.send_confirmation(db, sub, current_user):
        raise HTTPException(status_code=502, detail="Onay maili gönderilemedi")
    return _to_response(sub)


@router.post("/subscriptions/{subscription_id}/send-now", response_model=SendNowResponse, status_code=202)
def send_subscription_now(
    subscription_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Queue building + mailing this subscription's bulletin right away (owner or admin). It can
    take minutes — longer than the nginx proxy timeout — so the result lands in the delivery
    history. Costs OpenAI tokens, so it is limited to once an hour per subscription; a run that
    builds no bulletin gives the hour back."""
    sub = _get_accessible(db, subscription_id, current_user)
    if sub.status in ("pending", "unsubscribed"):
        raise HTTPException(status_code=400, detail="Onaylanmamış veya iptal edilmiş aboneliğe gönderim yapılamaz")
    if not email_service.is_configured():
        raise HTTPException(status_code=400, detail="E-posta gönderimi yapılandırılmamış")
    if sub.last_manual_send_at and _now() - sub.last_manual_send_at < newsletter_service.MANUAL_SEND_COOLDOWN:
        raise HTTPException(status_code=429, detail="Şimdi gönder en fazla saatte bir kez kullanılabilir")
    restore_to = newsletter_service.claim_manual_send(db, sub)
    background_tasks.add_task(newsletter_service.run_send_now, sub.id, restore_to)
    return SendNowResponse(status="queued")


@router.get("/subscriptions/{subscription_id}/deliveries", response_model=List[DeliveryResponse])
def list_deliveries(
    subscription_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    sub = _get_accessible(db, subscription_id, current_user)
    return crud.get_newsletter_deliveries(db, sub.id, limit=limit)


@router.get("/admin/subscriptions", response_model=AdminSubscriptionsResponse)
def list_all_subscriptions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    """Every user's subscriptions plus the newsletter LLM cost of the last 30 days (admin only)."""
    return AdminSubscriptionsResponse(
        subscriptions=[_to_response(s) for s in crud.get_newsletter_subscriptions(db)],
        cost_last_30_days=round(crud.get_newsletter_cost(db, _now() - timedelta(days=30)), 4),
        categories_missing=not crud.get_bulletin_categories(db),
    )


# ==================== Public routes (mail links) ====================

_TOKEN_QUERY = Query(..., min_length=10, max_length=128)


def _page(title: str, message: str, button: Optional[str] = None, action: Optional[str] = None) -> HTMLResponse:
    form = ""
    if button and action:
        form = (f'<form method="post" action="{html.escape(action, quote=True)}">'
                f'<button type="submit">{html.escape(button)}</button></form>')
    # Every page (also the results after the POST) offers a way back instead of a dead end.
    home = html.escape(settings.app_public_url.rstrip("/"), quote=True)
    back = f'<p class="back"><a href="{home}">Bülten\'e dön</a></p>'
    body = f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{html.escape(title)} – Bülten</title>
<style>
body{{margin:0;background:#f4f5f7;font-family:Arial,Helvetica,sans-serif;color:#1f2933}}
main{{max-width:480px;margin:64px auto;padding:32px 28px;background:#fff;border-radius:8px}}
h1{{font-size:22px;margin:0 0 12px}} p{{line-height:1.5}}
button{{background:#0b4f8a;color:#fff;border:0;border-radius:6px;padding:12px 20px;font-size:15px;cursor:pointer}}
.back{{margin:24px 0 0}} .back a{{color:#0b4f8a;font-weight:bold;text-decoration:none}}
</style></head>
<body><main><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>{form}{back}</main></body></html>"""
    return HTMLResponse(body)


def _action(path: str, token: str) -> str:
    return newsletter_service.public_url(path, token)


@public_router.get("/confirm", response_class=HTMLResponse)
def confirm_page(token: str = _TOKEN_QUERY, db: Session = Depends(get_db)):
    sub = crud.get_newsletter_subscription_by_confirm_token(db, token)
    if not sub or sub.status != "pending":
        return _page("Bağlantı geçersiz", "Bu onay bağlantısı geçersiz ya da daha önce kullanılmış.")
    if newsletter_service.confirmation_expired(sub):
        return _page("Bağlantının süresi dolmuş", "Abonelik sahibinden yeni bir onay maili göndermesini isteyin.")
    label = newsletter_service.FREQUENCY_LABELS[sub.frequency].lower()
    return _page(
        "Aboneliği onayla",
        f"{sub.email} adresine {label} Bülten gönderilmesini onaylıyor musunuz?",
        button="Aboneliği onayla",
        action=_action("confirm", token),
    )


@public_router.post("/confirm", response_class=HTMLResponse)
def confirm_subscription(token: str = _TOKEN_QUERY, db: Session = Depends(get_db)):
    sub = crud.get_newsletter_subscription_by_confirm_token(db, token)
    if not sub or sub.status != "pending":
        return _page("Bağlantı geçersiz", "Bu onay bağlantısı geçersiz ya da daha önce kullanılmış.")
    if newsletter_service.confirmation_expired(sub):
        return _page("Bağlantının süresi dolmuş", "Abonelik sahibinden yeni bir onay maili göndermesini isteyin.")
    crud.update_newsletter_subscription(
        db, sub, status="active", confirm_token=None, consecutive_failures=0, active_since=_now()
    )
    return _page("Abonelik onaylandı", "Bülten planlanan zamanda bu adrese gönderilecek. "
                 "Her mailin altındaki bağlantıyla istediğiniz zaman abonelikten çıkabilirsiniz.")


@public_router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str = _TOKEN_QUERY, db: Session = Depends(get_db)):
    sub = crud.get_newsletter_subscription_by_unsubscribe_token(db, token)
    if not sub:
        return _page("Bağlantı geçersiz", "Bu abonelik bulunamadı; silinmiş olabilir.")
    if sub.status == "unsubscribed":
        return _page("Abonelikten çıkıldı", "Bu adrese artık bülten gönderilmiyor.")
    return _page(
        "Abonelikten çık",
        f"{sub.email} adresine bülten gönderimini durdurmak istiyor musunuz?",
        button="Abonelikten çık",
        action=_action("unsubscribe", token),
    )


@public_router.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(token: str = _TOKEN_QUERY, db: Session = Depends(get_db)):
    """Also the RFC 8058 one-click target (List-Unsubscribe-Post) — the body is ignored."""
    sub = crud.get_newsletter_subscription_by_unsubscribe_token(db, token)
    if not sub:
        return _page("Bağlantı geçersiz", "Bu abonelik bulunamadı; silinmiş olabilir.")
    if sub.status != "unsubscribed":
        crud.update_newsletter_subscription(db, sub, status="unsubscribed", confirm_token=None)
    return _page("Abonelikten çıkıldı", "Bu adrese artık bülten gönderilmeyecek.")
