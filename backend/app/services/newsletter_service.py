"""
Bulletin subscriptions: periodic e-mail delivery of the Word bulletin.

Flow (driven hourly by the scheduler, see `run_scheduled_newsletters`):
1. every active subscription has a weekly/daily *slot* (send_hour[/send_weekday] in
   NEWSLETTER_TIMEZONE); one that is due — slot passed less than CATCH_UP_WINDOW ago, not yet
   sent, not before the subscription became active — is claimed atomically in the DB so the
   same slot is never sent twice;
2. due subscriptions are grouped by their content filters and each group's bulletin is built
   ONCE (`bulletin_service.build_bulletin_sections`, same pipeline and template as the manual
   Bülten › Oluştur button), then mailed to every subscriber of the group in their format;
3. no matching article / cost limit reached → a short info mail; SMTP failure → retried, then
   recorded as failed, and a subscription failing DISABLE_AFTER_FAILURES times in a row is disabled.

Article window: daily = the last 24 h, weekly = the last 7 days, counted back from the send time.
Selection: priority/favourite filter → high > med > low, then newest → only the subscribed
top-level categories (classification is cached, and stops once enough matched) → at most
`max_articles`.
"""
import asyncio
import html
import logging
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import CostLimitExceededError
from app.db import crud, models
from app.services import bulletin_service, email_service
from app.services.email_service import EmailAttachment, EmailNotConfiguredError, OutgoingEmail

logger = logging.getLogger(__name__)

FREQUENCY_WINDOWS = {"daily": timedelta(hours=24), "weekly": timedelta(days=7)}
FREQUENCY_LABELS = {"daily": "Günlük", "weekly": "Haftalık"}
_PRIORITY_LABELS = {"high": "Yüksek", "med": "Orta", "low": "Düşük"}
CATCH_UP_WINDOW = timedelta(hours=6)  # a slot missed while the server was down is still sent this late
MAX_SEND_ATTEMPTS = 3
RETRY_DELAYS_SECONDS = (5, 20)  # waits before the 2nd and 3rd attempt
DISABLE_AFTER_FAILURES = 3
CONFIRM_TOKEN_TTL = timedelta(days=7)
CONFIRM_RESEND_COOLDOWN = timedelta(hours=1)
MANUAL_SEND_COOLDOWN = timedelta(hours=1)
MAX_SUBSCRIPTIONS_PER_USER = 10
# Confirmation mails one user may trigger per hour, so deleting and re-creating a subscription
# can't turn the app into a mail cannon against a foreign address.
CONFIRMATION_MAILS_PER_HOUR = 5
# Candidates fetched (in priority order) before the category filter: bounds classification cost.
CANDIDATE_MULTIPLIER = 3

DOCX_MIME = ("application", "vnd.openxmlformats-officedocument.wordprocessingml.document")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.newsletter_timezone)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def latest_slot(sub: models.NewsletterSubscription, now: datetime) -> datetime:
    """The most recent scheduled send moment at or before `now` (UTC)."""
    local_now = now.astimezone(_tz())
    slot = local_now.replace(hour=sub.send_hour, minute=0, second=0, microsecond=0)
    if sub.frequency == "weekly":
        slot -= timedelta(days=(local_now.weekday() - (sub.send_weekday or 0)) % 7)
        if slot > local_now:
            slot -= timedelta(days=7)
    elif slot > local_now:
        slot -= timedelta(days=1)
    return slot.astimezone(timezone.utc)


def is_due(sub: models.NewsletterSubscription, now: datetime) -> bool:
    slot = latest_slot(sub, now)
    if now - slot > CATCH_UP_WINDOW:
        return False
    if sub.active_since is not None and slot < sub.active_since:
        return False
    return sub.last_sent_at is None or sub.last_sent_at < slot


# ---------------------------------------------------------------------------
# Article selection + building
# ---------------------------------------------------------------------------

def _priorities(sub: models.NewsletterSubscription) -> Optional[List[str]]:
    return [p for p in sub.priorities.split(",") if p] if sub.priorities else None


def content_key(sub: models.NewsletterSubscription) -> Tuple:
    """Subscriptions with the same key get the very same bulletin (built once)."""
    return (
        sub.frequency,
        sub.max_articles,
        tuple(sorted(_priorities(sub) or [])),
        bool(sub.include_favorites),
        tuple(sub.category_ids),
    )


async def select_articles(
    db: Session,
    sub: models.NewsletterSubscription,
    categories: List[models.BulletinCategory],
    start: datetime,
    end: datetime,
) -> List[models.Article]:
    """At most `sub.max_articles` articles: filter → priority, then newest → subscribed categories."""
    candidates = crud.get_bulletin_candidate_articles(
        db,
        start_date=start,
        end_date=end,
        priorities=_priorities(sub),
        include_favorites=sub.include_favorites,
        limit=settings.bulletin_max_articles * CANDIDATE_MULTIPLIER,
        order_by_priority=True,
    )
    category_names = [c.name for c in categories]
    wanted = {c.name for c in categories if c.id in set(sub.category_ids)}
    if not wanted:  # no filter, or every subscribed category was deleted → all categories
        return candidates[:sub.max_articles]

    selected: List[models.Article] = []
    batch_size = max(1, settings.bulletin_classification_batch_size)
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i:i + batch_size]
        # Classified from brief summaries (generated where missing), exactly like the bulletin itself
        # does — the result is cached and reused by every later bulletin.
        classifications = await bulletin_service.classify_for_bulletin(db, batch, categories)
        for article in batch:
            if bulletin_service.placement_category(classifications.get(article.id), category_names) in wanted:
                selected.append(article)
                if len(selected) >= sub.max_articles:
                    return selected
    return selected


@dataclass
class BuiltBulletin:
    """One group's bulletin. status: ok | no_articles | cost_limit | no_categories | error."""
    status: str
    window_from: datetime
    window_to: datetime
    article_count: int = 0
    sections: List[Dict] = field(default_factory=list)
    docx: Optional[bytes] = None
    cost: float = 0.0
    error: Optional[str] = None


def _docx_metadata(sub: models.NewsletterSubscription, categories: List[models.BulletinCategory],
                   window_from: datetime, window_to: datetime) -> Dict[str, str]:
    tz = _tz()
    wanted = [c.name for c in categories if c.id in set(sub.category_ids)] or [c.name for c in categories]
    label = FREQUENCY_LABELS[sub.frequency]
    filters = [
        f"Tarih aralığı: {window_from.astimezone(tz):%d.%m.%Y %H:%M} – {window_to.astimezone(tz):%d.%m.%Y %H:%M}",
        f"Önem: {_selection_label(sub)}",
        f"Kategoriler: {', '.join(wanted)}",
        f"En fazla haber: {sub.max_articles}",
    ]
    return {
        "title": f"{label} Bülten – {window_to.astimezone(tz):%d.%m.%Y}",
        "subject": f"{label} haber bülteni",
        "keywords": ", ".join(wanted),
        "comments": "\n".join(filters),
        "category": f"{label} Bülten",
    }


def _selection_label(sub: models.NewsletterSubscription) -> str:
    """Mirrors crud._bulletin_candidate_filter: priorities OR favourites; favourites alone = only them."""
    priorities = ", ".join(_PRIORITY_LABELS[p] for p in (_priorities(sub) or []) if p in _PRIORITY_LABELS)
    if priorities:
        return priorities + (" + Favoriler" if sub.include_favorites else "")
    return "Yalnızca favoriler" if sub.include_favorites else "Tümü"


async def build_bulletin(db: Session, sub: models.NewsletterSubscription, now: datetime) -> BuiltBulletin:
    """Select + build + render the bulletin `sub` (and every subscription with its content_key) gets."""
    window_to = now
    window_from = now - FREQUENCY_WINDOWS[sub.frequency]
    built = BuiltBulletin(status="ok", window_from=window_from, window_to=window_to)

    categories = crud.get_bulletin_categories(db)
    if not categories:
        built.status = "no_categories"
        return built

    started = _utcnow()
    try:
        articles = await select_articles(db, sub, categories, window_from, window_to)
        if not articles:
            built.status = "no_articles"
            return built
        built.sections = await bulletin_service.build_bulletin_sections(db, articles, categories)
        built.article_count = len(articles)
        built.docx = bulletin_service.render_bulletin_report(
            db, built.sections, generated_at=now,
            metadata=_docx_metadata(sub, categories, window_from, window_to),
        ).getvalue()
    except CostLimitExceededError as e:
        built.status = "cost_limit"
        built.error = str(e)
    except Exception as e:  # BulletinGenerationError or anything else: one bad group must not stop the run
        logger.error(f"Newsletter: building bulletin for subscription {sub.id} failed: {e}", exc_info=True)
        built.status = "error"
        built.error = str(e)
    finally:
        # Approximate: LLM calls booked meanwhile by the bulletin pipeline (incl. its brief summaries).
        ended = _utcnow()
        built.cost = sum(crud.get_total_cost(db, start_date=started, end_date=ended, kind=kind)
                         for kind in ("bulletin", "summary"))
    return built


# ---------------------------------------------------------------------------
# Mail rendering
# ---------------------------------------------------------------------------

def public_url(path: str, token: str) -> str:
    return f"{settings.app_public_url.rstrip('/')}/api/newsletter/public/{path}?{urlencode({'token': token})}"


def _safe_href(url: Optional[str]) -> Optional[str]:
    if url and urlparse(url).scheme in ("http", "https"):
        return html.escape(url, quote=True)
    return None


def _subject(sub: models.NewsletterSubscription, built: BuiltBulletin) -> str:
    tz = _tz()
    label = FREQUENCY_LABELS[sub.frequency]
    to_ = built.window_to.astimezone(tz)
    if sub.frequency == "weekly":
        from_ = built.window_from.astimezone(tz)
        return f"{label} Bülten – {from_:%d.%m}–{to_:%d.%m.%Y}"
    return f"{label} Bülten – {to_:%d.%m.%Y}"


_WRAPPER = (
    '<!doctype html><html lang="tr"><head><meta charset="utf-8"></head>'
    '<body style="margin:0;padding:0;background:#f4f5f7;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f5f7;">'
    '<tr><td align="center" style="padding:24px 12px;">'
    '<table role="presentation" width="640" cellpadding="0" cellspacing="0" '
    'style="max-width:640px;width:100%;background:#ffffff;border-radius:8px;'
    'font-family:Arial,Helvetica,sans-serif;color:#1f2933;font-size:15px;line-height:1.5;">'
    '<tr><td style="padding:24px 28px;">{body}</td></tr></table></td></tr></table></body></html>'
)


def _footer_html(unsubscribe_url: str) -> str:
    return (
        '<hr style="border:none;border-top:1px solid #e4e7eb;margin:28px 0 12px;">'
        '<p style="font-size:12px;color:#7b8794;margin:0;">Bu maili Bülten aboneliğiniz nedeniyle alıyorsunuz. '
        f'<a href="{html.escape(unsubscribe_url, quote=True)}" style="color:#7b8794;">Abonelikten çık</a></p>'
    )


def _footer_text(unsubscribe_url: str) -> str:
    return f"\n\n--\nBu maili Bülten aboneliğiniz nedeniyle alıyorsunuz.\nAbonelikten çık: {unsubscribe_url}\n"


def render_bulletin_email(
    sub: models.NewsletterSubscription, built: BuiltBulletin, unsubscribe_url: str
) -> Tuple[str, str]:
    """(html, text) body. "email"/"both" carry the whole bulletin; "docx" only points to the attachment."""
    title = _subject(sub, built)
    parts = [f'<h1 style="font-size:22px;margin:0 0 4px;">{html.escape(title)}</h1>',
             f'<p style="color:#52606d;margin:0 0 20px;">{built.article_count} haber</p>']
    text = [title, f"{built.article_count} haber", ""]

    if sub.delivery_format == "docx":
        parts.append("<p>Bülteniniz bu mailin ekinde Word dosyası olarak yer alıyor.</p>")
        text.append("Bülteniniz bu mailin ekinde Word dosyası olarak yer alıyor.")
    else:
        if sub.delivery_format == "both":
            parts.append('<p style="color:#52606d;">Word dosyası ektedir.</p>')
            text.extend(["Word dosyası ektedir.", ""])
        for section in built.sections:
            if not any(group["items"] for group in section["groups"]):
                continue
            parts.append(
                f'<h2 style="font-size:18px;color:#0b4f8a;border-bottom:2px solid #0b4f8a;'
                f'padding-bottom:4px;margin:28px 0 8px;">{html.escape(section["title"])}</h2>'
            )
            text.extend(["", section["title"].upper(), "=" * len(section["title"])])
            for group in section["groups"]:
                parts.append(f'<h3 style="font-size:15px;margin:18px 0 6px;">{html.escape(group["title"])}</h3>')
                text.extend(["", group["title"]])
                for item in group["items"]:
                    href = _safe_href(item.get("url"))
                    header = html.escape(item["header"])
                    if href:
                        header = f'<a href="{href}" style="color:#1f2933;text-decoration:none;">{header}</a>'
                    parts.append(f'<p style="font-weight:bold;margin:12px 0 4px;">{header}</p>')
                    text.append(item["header"])
                    for bullet in item.get("bullets", []):
                        parts.append(f'<p style="margin:2px 0 2px 12px;">{html.escape(bullet)}</p>')
                        text.append(f"  {bullet}")
                    if href:
                        parts.append(f'<p style="margin:2px 0 0 12px;font-size:13px;">'
                                     f'<a href="{href}" style="color:#0b4f8a;">Habere git →</a></p>')
                        text.append(f"  {item['url']}")
    parts.append(_footer_html(unsubscribe_url))
    return _WRAPPER.replace("{body}", "".join(parts)), "\n".join(text) + _footer_text(unsubscribe_url)


_INFO_MESSAGES = {
    "no_articles": "Bu dönem için abonelik kriterlerinize uygun haber bulunamadı. Bir sonraki bülten planlandığı gibi gönderilecek.",
    "cost_limit": "Bu dönemin bülteni, yapay zekâ kullanım limiti dolduğu için hazırlanamadı. Bir sonraki bülten planlandığı gibi gönderilecek.",
}


def render_info_email(
    sub: models.NewsletterSubscription, built: BuiltBulletin, unsubscribe_url: str
) -> Tuple[str, str, str]:
    """(subject, html, text) for a period without a bulletin."""
    subject = f"{_subject(sub, built)}: bülten hazırlanamadı" if built.status == "cost_limit" \
        else f"{_subject(sub, built)}: haber yok"
    message = _INFO_MESSAGES[built.status]
    body = (f'<h1 style="font-size:20px;margin:0 0 12px;">{html.escape(_subject(sub, built))}</h1>'
            f"<p>{html.escape(message)}</p>{_footer_html(unsubscribe_url)}")
    return subject, _WRAPPER.replace("{body}", body), f"{_subject(sub, built)}\n\n{message}{_footer_text(unsubscribe_url)}"


def _unsubscribe_headers(unsubscribe_url: str) -> Dict[str, str]:
    # RFC 8058 one-click: mail clients POST "List-Unsubscribe=One-Click" to this URL.
    return {"List-Unsubscribe": f"<{unsubscribe_url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


def compose_mail(sub: models.NewsletterSubscription, built: BuiltBulletin) -> OutgoingEmail:
    unsubscribe_url = public_url("unsubscribe", sub.unsubscribe_token)
    headers = _unsubscribe_headers(unsubscribe_url)
    if built.status in _INFO_MESSAGES:
        subject, html_body, text_body = render_info_email(sub, built, unsubscribe_url)
        return OutgoingEmail(to=sub.email, subject=subject, text=text_body, html=html_body, headers=headers)

    html_body, text_body = render_bulletin_email(sub, built, unsubscribe_url)
    attachments = []
    if sub.delivery_format in ("docx", "both") and built.docx:
        stamp = built.window_to.astimezone(_tz()).strftime("%Y-%m-%d")
        kind = "gunluk" if sub.frequency == "daily" else "haftalik"
        attachments.append(EmailAttachment(
            filename=f"bulten-{kind}-{stamp}.docx", content=built.docx,
            maintype=DOCX_MIME[0], subtype=DOCX_MIME[1],
        ))
    return OutgoingEmail(to=sub.email, subject=_subject(sub, built), text=text_body, html=html_body,
                         attachments=attachments, headers=headers)


def compose_confirmation_mail(sub: models.NewsletterSubscription, requested_by: str) -> OutgoingEmail:
    confirm_url = public_url("confirm", sub.confirm_token)
    label = FREQUENCY_LABELS[sub.frequency].lower()
    message = (f"{requested_by} bu adres için {label} Bülten aboneliği oluşturdu. "
               "Abone olmak istiyorsanız aşağıdaki bağlantıdan onaylayın. "
               f"Bağlantı {CONFIRM_TOKEN_TTL.days} gün geçerlidir; onaylamazsanız size hiç mail gönderilmez.")
    body = (
        '<h1 style="font-size:20px;margin:0 0 12px;">Bülten aboneliğinizi onaylayın</h1>'
        f"<p>{html.escape(message)}</p>"
        f'<p style="margin:24px 0;"><a href="{html.escape(confirm_url, quote=True)}" '
        'style="background:#0b4f8a;color:#ffffff;padding:12px 20px;border-radius:6px;'
        'text-decoration:none;font-weight:bold;">Aboneliği onayla</a></p>'
        '<p style="font-size:12px;color:#7b8794;">Bu isteği siz yapmadıysanız bu maili yok sayabilirsiniz.</p>'
    )
    text = (f"Bülten aboneliğinizi onaylayın\n\n{message}\n\nOnayla: {confirm_url}\n\n"
            "Bu isteği siz yapmadıysanız bu maili yok sayabilirsiniz.\n")
    return OutgoingEmail(to=sub.email, subject="Bülten aboneliğinizi onaylayın", text=text,
                         html=_WRAPPER.replace("{body}", body))


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

async def send_with_retry(mail: OutgoingEmail) -> Tuple[bool, int, Optional[str]]:
    """(sent, attempts, last error). A missing SMTP configuration is not retried."""
    last_error: Optional[str] = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            await email_service.send_email(mail)
            return True, attempt, None
        except EmailNotConfiguredError as e:
            return False, attempt, str(e)
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            logger.warning(f"Newsletter: send attempt {attempt} failed: {last_error}")
            if attempt < MAX_SEND_ATTEMPTS:
                await asyncio.sleep(RETRY_DELAYS_SECONDS[min(attempt - 1, len(RETRY_DELAYS_SECONDS) - 1)])
    return False, MAX_SEND_ATTEMPTS, last_error


_STATUS_FOR_BUILD = {
    "no_articles": "skipped_no_articles",
    "cost_limit": "skipped_cost_limit",
    "no_categories": "skipped_no_categories",
    "error": "skipped_build_error",
}


async def deliver(
    db: Session,
    sub: models.NewsletterSubscription,
    built: BuiltBulletin,
    manual: bool = False,
    cost: float = 0.0,
) -> models.NewsletterDelivery:
    """Mail `built` to `sub`, record the delivery and update the failure counter."""
    if built.status == "no_categories":
        # Admin-side problem (no top-level category defined): nothing is mailed to the subscriber.
        return crud.create_newsletter_delivery(
            db, sub.id, "skipped_no_categories", manual=manual, attempts=0,
            error="Hiç üst düzey kategori tanımlı değil",
        )
    if built.status == "error":
        # Our side failed (LLM, template…), not the subscriber's address: no mail, and it doesn't
        # count towards DISABLE_AFTER_FAILURES.
        return crud.create_newsletter_delivery(
            db, sub.id, "skipped_build_error", manual=manual, attempts=0, cost=cost, error=built.error,
        )

    sent, attempts, error = await send_with_retry(compose_mail(sub, built))
    status = _STATUS_FOR_BUILD.get(built.status, "sent")
    if not sent:
        return _record_failure(db, sub, built, manual, cost, attempts=attempts, error=error)
    crud.update_newsletter_subscription(db, sub, consecutive_failures=0)
    return crud.create_newsletter_delivery(
        db, sub.id, status, article_count=built.article_count, attempts=attempts, manual=manual,
        cost=cost, error=built.error if status != "sent" else None,
    )


def _record_failure(db: Session, sub: models.NewsletterSubscription, built: BuiltBulletin,
                    manual: bool, cost: float, attempts: int, error: Optional[str]) -> models.NewsletterDelivery:
    failures = (sub.consecutive_failures or 0) + 1
    fields = {"consecutive_failures": failures}
    if failures >= DISABLE_AFTER_FAILURES:
        fields["status"] = "disabled"
        logger.warning(f"Newsletter: subscription {sub.id} disabled after {failures} consecutive failures")
    crud.update_newsletter_subscription(db, sub, **fields)
    return crud.create_newsletter_delivery(
        db, sub.id, "failed", article_count=built.article_count, attempts=attempts, manual=manual,
        cost=cost, error=error,
    )


# In-process, like core/rate_limit.py: enough for the single-process deployment.
_confirmation_mail_times: Dict[int, List[float]] = {}


def _recent_confirmation_mails(user_id: int) -> List[float]:
    cutoff = time.monotonic() - 3600
    recent = [t for t in _confirmation_mail_times.get(user_id, []) if t > cutoff]
    _confirmation_mail_times[user_id] = recent
    return recent


def confirmation_quota_left(user_id: int) -> bool:
    return len(_recent_confirmation_mails(user_id)) < CONFIRMATION_MAILS_PER_HOUR


async def send_confirmation(db: Session, sub: models.NewsletterSubscription, requester: models.User) -> bool:
    """Mail the double opt-in link (single attempt — runs inside a request). Records
    confirm_sent_at on success, which the UI uses to tell "mail sent" from "mail failed".
    Routes check `confirmation_quota_left` first; an exhausted quota just skips the mail."""
    if not confirmation_quota_left(requester.id):
        return False
    try:
        await email_service.send_email(compose_confirmation_mail(sub, requester.email))
    except Exception as e:
        logger.warning(f"Newsletter: confirmation mail for subscription {sub.id} failed: {e}")
        return False
    _recent_confirmation_mails(requester.id).append(time.monotonic())
    crud.update_newsletter_subscription(db, sub, confirm_sent_at=_utcnow())
    return True


def confirmation_expired(sub: models.NewsletterSubscription, now: Optional[datetime] = None) -> bool:
    # Without a sent mail, the moment it (re)entered "pending" — updated_at — not its creation.
    sent = sub.confirm_sent_at or sub.updated_at or sub.created_at
    return sent is not None and (now or _utcnow()) - sent > CONFIRM_TOKEN_TTL


def _new_session() -> Session:
    """Background jobs open their own session (tests swap this for the test session)."""
    from app.db.database import SessionLocal

    return SessionLocal()


def claim_manual_send(db: Session, sub: models.NewsletterSubscription) -> Optional[datetime]:
    """Start the hourly "Şimdi gönder" window right away (so a double click can't start two
    builds); returns the previous value for `send_now` to restore."""
    previous = sub.last_manual_send_at
    crud.update_newsletter_subscription(db, sub, last_manual_send_at=_utcnow())
    return previous


async def send_now(
    db: Session, sub: models.NewsletterSubscription, restore_to: Optional[datetime] = None
) -> models.NewsletterDelivery:
    """"Şimdi gönder": build and mail this subscription's bulletin right away (no slot claimed).
    The hourly limit exists to bound OpenAI cost, so the window claimed by `claim_manual_send` is
    given back (`restore_to`) when no bulletin was built: no articles, no categories, cost limit,
    build error."""
    built = await build_bulletin(db, sub, _utcnow())
    if built.status != "ok":
        crud.update_newsletter_subscription(db, sub, last_manual_send_at=restore_to)
    return await deliver(db, sub, built, manual=True, cost=built.cost)


async def run_send_now(subscription_id: int, restore_to: Optional[datetime] = None) -> None:
    """Background task behind POST .../send-now: building can take minutes — longer than the
    nginx proxy timeout — so the request only queues it. Never raises."""
    db = _new_session()
    try:
        sub = crud.get_newsletter_subscription(db, subscription_id)
        if sub is not None:
            await send_now(db, sub, restore_to)
    except Exception as e:
        logger.error(f"Newsletter: send-now for subscription {subscription_id} failed: {e}", exc_info=True)
    finally:
        db.close()


async def send_due_newsletters(db: Session, now: Optional[datetime] = None) -> int:
    """One scheduler tick: claim every due subscription's slot, build once per content group, mail.
    Returns the number of deliveries recorded."""
    now = now or _utcnow()
    expired = crud.delete_expired_pending_newsletter_subscriptions(db, now - CONFIRM_TOKEN_TTL)
    if expired:
        logger.info(f"Newsletter: removed {expired} unconfirmed subscription(s)")

    if not email_service.is_configured():
        logger.info("Newsletter: SMTP is not configured, skipping this run")
        return 0

    claimed: List[models.NewsletterSubscription] = [
        sub for sub in crud.get_sendable_newsletter_subscriptions(db)
        if is_due(sub, now) and crud.claim_newsletter_slot(db, sub.id, latest_slot(sub, now))
    ]
    if not claimed:
        return 0

    groups: Dict[Tuple, List[models.NewsletterSubscription]] = {}
    for sub in claimed:
        groups.setdefault(content_key(sub), []).append(sub)
    logger.info(f"Newsletter: {len(claimed)} due subscription(s) in {len(groups)} group(s)")

    count = 0
    for members in groups.values():
        built = await build_bulletin(db, members[0], now)
        share = built.cost / len(members)
        for sub in members:
            try:
                await deliver(db, sub, built, cost=share)
                count += 1
            except Exception as e:
                logger.error(f"Newsletter: delivering subscription {sub.id} failed: {e}", exc_info=True)
    return count


async def run_scheduled_newsletters() -> None:
    """Scheduler entry point: own session (background code), never raises."""
    db = _new_session()
    try:
        await send_due_newsletters(db)
    except Exception as e:
        logger.error(f"Newsletter run failed: {e}", exc_info=True)
    finally:
        db.close()
