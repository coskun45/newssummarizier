"""
Tests for bulletin subscriptions: app/api/routes/newsletter.py and app/services/newsletter_service.py.
No test talks to SMTP or OpenAI: mails are captured, the bulletin LLM steps are stubbed.
"""
import asyncio
import io
from datetime import datetime, timedelta, timezone

import pytest
from docx import Document as DocxDocument

from app.core.config import settings as app_settings
from app.core.exceptions import CostLimitExceededError
from app.core.security import hash_password
from app.db import crud, models
from app.services import bulletin_service, newsletter_service, summary_service
from tests.conftest import _make_article, _make_feed

# Friday 2026-10-02 08:10 in Europe/Berlin (CEST, UTC+2).
NOW = datetime(2026, 10, 2, 6, 10, tzinfo=timezone.utc)


# ==================== Fixtures ====================

@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """SMTP "configured", every sent mail captured; retries don't actually wait."""
    sent = []

    async def fake_send(mail):
        sent.append(mail)

    monkeypatch.setattr(app_settings, "smtp_host", "smtp.test")
    # Pinned: the real value comes from the developer's .env.
    monkeypatch.setattr(app_settings, "newsletter_timezone", "Europe/Berlin")
    monkeypatch.setattr(app_settings, "smtp_from", "Bülten <bulten@example.com>")
    monkeypatch.setattr(app_settings, "app_public_url", "https://bulten.example.com")
    monkeypatch.setattr(newsletter_service.email_service, "send_email", fake_send)
    monkeypatch.setattr(newsletter_service, "RETRY_DELAYS_SECONDS", (0, 0))
    return sent


class _SharedSession:
    """The test session for background jobs; their close() must not end it for the test."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _background_jobs_use_test_session(monkeypatch, db_session):
    monkeypatch.setattr(newsletter_service, "_new_session", lambda: _SharedSession(db_session), raising=False)


@pytest.fixture(autouse=True)
def _fresh_confirmation_quota(monkeypatch):
    monkeypatch.setattr(newsletter_service, "_confirmation_mail_times", {})


@pytest.fixture(autouse=True)
def bulletin_llm(monkeypatch):
    """Classification puts "ASYA: ..." titles into ASYA, everything else into the first category.
    Records how often the bulletin is built."""
    calls = {"build": 0, "classified": [], "blocks": {}}

    async def fake_classify(db, articles, category_names, blocks=None):
        calls["classified"].extend(a.id for a in articles)
        calls["blocks"].update(blocks or {})
        result = []
        for a in articles:
            prefix = a.title.split(":", 1)[0] if ":" in a.title else None
            result.append({"article_id": a.id,
                           "top_category": prefix if prefix in category_names else category_names[0],
                           "subcategory": "", "type": "haber"})
        return result

    async def no_highlights(articles, blocks, limit=bulletin_service.HIGHLIGHT_LIMIT):
        return []

    async def single_group(category_name, articles, blocks):
        return [{"title": f"{category_name} GÜNDEMİ", "article_ids": [a.id for a in articles]}] if articles else []

    async def fake_summary(title, content, summary_type="standard", source=None, author_hint=None):
        return {"summary_text": f"📌 **DW - {title}**\n🔹 {title} özeti.", "model_used": "gpt-test",
                "tokens_used": 1, "cost": 0.0, "author": None, "structured": True}

    async def no_cost_limits():
        return None

    real_build = bulletin_service.build_bulletin_sections

    async def counting_build(db, articles, categories):
        calls["build"] += 1
        return await real_build(db, articles, categories)

    monkeypatch.setattr(bulletin_service, "classify_articles_for_bulletin", fake_classify)
    monkeypatch.setattr(bulletin_service, "pick_bulletin_highlights", no_highlights)
    monkeypatch.setattr(bulletin_service, "group_category_articles", single_group)
    monkeypatch.setattr(bulletin_service, "check_cost_limits", no_cost_limits)
    monkeypatch.setattr(bulletin_service, "build_bulletin_sections", counting_build)
    monkeypatch.setattr(summary_service, "generate_summary", fake_summary)
    return calls


def _category(db_session, name, order=0):
    row = models.BulletinCategory(name=name, display_order=order)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _body(**overrides):
    body = {
        "email": "tester@example.com",
        "frequency": "daily",
        "send_hour": 8,
        "send_weekday": None,
        "max_articles": 10,
        "priorities": [],
        "include_favorites": False,
        "category_ids": [],
        "delivery_format": "both",
    }
    body.update(overrides)
    return body


def _create(client, headers, **overrides):
    return client.post("/api/newsletter/subscriptions", json=_body(**overrides), headers=headers)


def _subscription(db_session, user, *, email=None, frequency="daily", send_hour=8, send_weekday=None,
                  max_articles=10, priorities=None, include_favorites=False, delivery_format="both",
                  category_ids=(), status="active", active_since=NOW - timedelta(days=30), last_sent_at=None):
    sub = crud.create_newsletter_subscription(
        db_session, user_id=user.id, email=email or user.email, frequency=frequency, send_hour=send_hour,
        send_weekday=send_weekday, max_articles=max_articles, priorities=priorities,
        include_favorites=include_favorites, delivery_format=delivery_format, category_ids=list(category_ids),
        status=status, unsubscribe_token=newsletter_service.new_token(),
        confirm_token=newsletter_service.new_token() if status == "pending" else None,
        active_since=active_since,
    )
    if last_sent_at:
        crud.update_newsletter_subscription(db_session, sub, last_sent_at=last_sent_at)
    return sub


def _articles(db_session, *specs, now=NOW):
    """specs: (title, priority, hours_ago)."""
    feed = _make_feed(db_session)
    return [_make_article(db_session, feed.id, title=title, priority=priority,
                          published_at=now - timedelta(hours=hours_ago), status="summarized")
            for title, priority, hours_ago in specs]


def _run(db_session, now=NOW):
    return asyncio.run(newsletter_service.send_due_newsletters(db_session, now=now))


# ==================== Auth & create ====================

def test_endpoints_require_auth(client):
    assert client.get("/api/newsletter/subscriptions").status_code == 401
    assert client.post("/api/newsletter/subscriptions", json=_body()).status_code == 401
    assert client.get("/api/newsletter/admin/subscriptions").status_code == 401


def test_status_reports_configuration(client, auth_headers, monkeypatch):
    data = client.get("/api/newsletter/status", headers=auth_headers).json()
    assert data["email_configured"] is True
    assert data["max_articles_limit"] == app_settings.bulletin_max_articles
    monkeypatch.setattr(app_settings, "smtp_host", "")
    assert client.get("/api/newsletter/status", headers=auth_headers).json()["email_configured"] is False


def test_own_address_is_active_immediately_without_mail(client, auth_headers, outbox):
    response = _create(client, auth_headers, email="Tester@Example.com ")
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "active"
    assert data["email"] == "tester@example.com"
    assert outbox == []
    assert "token" not in str(data).lower()


def test_other_address_needs_confirmation_mail(client, auth_headers, outbox, db_session):
    response = _create(client, auth_headers, email="colleague@example.com")
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "pending"
    assert data["confirm_sent_at"] is not None
    assert len(outbox) == 1
    mail = outbox[0]
    assert mail.to == "colleague@example.com"
    sub = crud.get_newsletter_subscription(db_session, data["id"])
    assert f"/api/newsletter/public/confirm?token={sub.confirm_token}" in mail.text
    assert "tester@example.com" in mail.text  # who asked for it


def test_failed_confirmation_mail_leaves_confirm_sent_at_empty(client, auth_headers, monkeypatch):
    async def broken(mail):
        raise OSError("connection refused")

    monkeypatch.setattr(newsletter_service.email_service, "send_email", broken)
    data = _create(client, auth_headers, email="colleague@example.com").json()
    assert data["status"] == "pending"
    assert data["confirm_sent_at"] is None


@pytest.mark.parametrize("overrides, status", [
    ({"frequency": "weekly", "send_weekday": None}, 400),
    ({"max_articles": 51}, 400),
    ({"max_articles": 0}, 422),
    ({"category_ids": [999]}, 400),
    ({"email": "not-an-email"}, 400),
    ({"email": "a@b"}, 400),
    ({"frequency": "monthly"}, 422),
    ({"send_hour": 24}, 422),
    ({"send_weekday": 7, "frequency": "weekly"}, 422),
    ({"priorities": ["urgent"]}, 422),
    ({"delivery_format": "pdf"}, 422),
])
def test_create_validation(client, auth_headers, overrides, status):
    assert _create(client, auth_headers, **overrides).status_code == status


def test_duplicate_subscription_rejected(client, auth_headers):
    assert _create(client, auth_headers, priorities=["high", "med"]).status_code == 201
    response = _create(client, auth_headers, priorities=["med", "high"])
    assert response.status_code == 400
    assert "aynı ayarlarla" in response.json()["detail"]
    # A different setting is a different subscription.
    assert _create(client, auth_headers, priorities=["high"]).status_code == 201


def test_per_user_subscription_limit(client, auth_headers, monkeypatch):
    monkeypatch.setattr(newsletter_service, "MAX_SUBSCRIPTIONS_PER_USER", 2)
    assert _create(client, auth_headers, send_hour=1).status_code == 201
    assert _create(client, auth_headers, send_hour=2).status_code == 201
    response = _create(client, auth_headers, send_hour=3)
    assert response.status_code == 400
    assert "En fazla 2" in response.json()["detail"]


def test_weekly_subscription_keeps_weekday_daily_drops_it(client, auth_headers):
    weekly = _create(client, auth_headers, frequency="weekly", send_weekday=0).json()
    assert weekly["send_weekday"] == 0
    daily = _create(client, auth_headers, send_weekday=3).json()
    assert daily["send_weekday"] is None


# ==================== Ownership & admin ====================

def test_users_only_see_and_touch_their_own(client, auth_headers, admin_headers, admin_user, db_session):
    other = _subscription(db_session, admin_user)
    mine = _create(client, auth_headers).json()

    listed = client.get("/api/newsletter/subscriptions", headers=auth_headers).json()
    assert [s["id"] for s in listed] == [mine["id"]]

    for method, path in [("put", f"/api/newsletter/subscriptions/{other.id}"),
                         ("delete", f"/api/newsletter/subscriptions/{other.id}"),
                         ("post", f"/api/newsletter/subscriptions/{other.id}/pause"),
                         ("post", f"/api/newsletter/subscriptions/{other.id}/send-now"),
                         ("get", f"/api/newsletter/subscriptions/{other.id}/deliveries")]:
        kwargs = {"headers": auth_headers}
        if method == "put":
            kwargs["json"] = _body()
        assert getattr(client, method)(path, **kwargs).status_code == 404, path

    # Admin sees everyone's and can manage them.
    data = client.get("/api/newsletter/admin/subscriptions", headers=admin_headers).json()
    assert {s["id"] for s in data["subscriptions"]} == {other.id, mine["id"]}
    assert {s["owner_email"] for s in data["subscriptions"]} == {"admin@example.com", "tester@example.com"}
    assert data["categories_missing"] is True
    assert client.post(f"/api/newsletter/subscriptions/{mine['id']}/pause", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/newsletter/subscriptions/{mine['id']}", headers=admin_headers).status_code == 200


def test_not_found(client, auth_headers):
    assert client.delete("/api/newsletter/subscriptions/999", headers=auth_headers).status_code == 404


def test_deleting_user_deletes_their_subscriptions(db_session, test_user):
    sub = _subscription(db_session, test_user)
    crud.create_newsletter_delivery(db_session, sub.id, "sent")
    assert crud.delete_user(db_session, test_user.id)
    assert db_session.query(models.NewsletterSubscription).count() == 0
    assert db_session.query(models.NewsletterDelivery).count() == 0


# ==================== Update / pause / resume ====================

def test_update_to_foreign_address_requires_confirmation(client, auth_headers, outbox):
    sub = _create(client, auth_headers).json()
    response = client.put(f"/api/newsletter/subscriptions/{sub['id']}",
                          json=_body(email="boss@example.com"), headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert [m.to for m in outbox] == ["boss@example.com"]


def test_update_schedule_does_not_backfill_passed_slot(client, auth_headers, db_session):
    sub = _create(client, auth_headers).json()
    before = crud.get_newsletter_subscription(db_session, sub["id"]).active_since
    client.put(f"/api/newsletter/subscriptions/{sub['id']}", json=_body(send_hour=6), headers=auth_headers)
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub["id"]).active_since > before


def test_pause_and_resume(client, auth_headers):
    sub = _create(client, auth_headers).json()
    paused = client.post(f"/api/newsletter/subscriptions/{sub['id']}/pause", headers=auth_headers)
    assert paused.json()["status"] == "paused"
    assert client.post(f"/api/newsletter/subscriptions/{sub['id']}/pause", headers=auth_headers).status_code == 400
    resumed = client.post(f"/api/newsletter/subscriptions/{sub['id']}/resume", headers=auth_headers)
    assert resumed.json()["status"] == "active"
    assert client.post(f"/api/newsletter/subscriptions/{sub['id']}/resume", headers=auth_headers).status_code == 400


def test_resuming_a_recipient_who_unsubscribed_needs_new_confirmation(client, auth_headers, db_session, outbox, test_user):
    sub = _subscription(db_session, test_user, email="colleague@example.com", status="unsubscribed")
    response = client.post(f"/api/newsletter/subscriptions/{sub.id}/resume", headers=auth_headers)
    assert response.json()["status"] == "pending"
    assert [m.to for m in outbox] == ["colleague@example.com"]


def test_confirmation_mails_per_user_are_capped(client, auth_headers, outbox, monkeypatch):
    """Delete + re-create must not allow unlimited confirmation mails to a foreign address."""
    monkeypatch.setattr(newsletter_service, "CONFIRMATION_MAILS_PER_HOUR", 2)
    for _ in range(2):
        sub = _create(client, auth_headers, email="victim@example.com").json()
        client.delete(f"/api/newsletter/subscriptions/{sub['id']}", headers=auth_headers)
    response = _create(client, auth_headers, email="victim@example.com")
    assert response.status_code == 429
    assert len(outbox) == 2
    # The user's own address needs no confirmation, so it is not affected.
    assert _create(client, auth_headers).status_code == 201


def test_resume_respects_subscription_limit(client, auth_headers, db_session, test_user, monkeypatch):
    """Regression: unsubscribed rows don't count against the cap, and resume re-activated them unchecked."""
    monkeypatch.setattr(newsletter_service, "MAX_SUBSCRIPTIONS_PER_USER", 1)
    _subscription(db_session, test_user, send_hour=6)
    old = _subscription(db_session, test_user, send_hour=7, status="unsubscribed")
    response = client.post(f"/api/newsletter/subscriptions/{old.id}/resume", headers=auth_headers)
    assert response.status_code == 400
    assert "En fazla 1" in response.json()["detail"]


def test_resume_refuses_to_create_a_duplicate(client, auth_headers, db_session, test_user):
    _subscription(db_session, test_user)
    old = _subscription(db_session, test_user, status="unsubscribed")  # same settings
    response = client.post(f"/api/newsletter/subscriptions/{old.id}/resume", headers=auth_headers)
    assert response.status_code == 400
    assert "aynı ayarlarla" in response.json()["detail"]
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, old.id).status == "unsubscribed"


def test_resend_confirmation_cooldown(client, auth_headers):
    sub = _create(client, auth_headers, email="colleague@example.com").json()
    response = client.post(f"/api/newsletter/subscriptions/{sub['id']}/resend-confirmation", headers=auth_headers)
    assert response.status_code == 429


# ==================== Public confirm / unsubscribe ====================

def test_confirm_get_shows_button_only_post_confirms(client, auth_headers, db_session):
    sub_id = _create(client, auth_headers, email="colleague@example.com").json()["id"]
    token = crud.get_newsletter_subscription(db_session, sub_id).confirm_token

    page = client.get(f"/api/newsletter/public/confirm?token={token}")
    assert page.status_code == 200
    assert "Aboneliği onayla" in page.text and 'method="post"' in page.text
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub_id).status == "pending"

    done = client.post(f"/api/newsletter/public/confirm?token={token}")
    assert "onaylandı" in done.text
    db_session.expire_all()
    sub = crud.get_newsletter_subscription(db_session, sub_id)
    assert sub.status == "active" and sub.confirm_token is None
    # The link is single-use.
    assert "geçersiz" in client.post(f"/api/newsletter/public/confirm?token={token}").text


def test_public_result_pages_link_back_to_the_app(client, db_session, test_user):
    """Regression: after confirming/unsubscribing the page was a dead end with no way back to the app."""
    pending = _subscription(db_session, test_user, email="colleague@example.com", status="pending")
    active = _subscription(db_session, test_user)
    back_link = 'href="https://bulten.example.com"'
    pages = [
        client.post(f"/api/newsletter/public/confirm?token={pending.confirm_token}"),
        client.post(f"/api/newsletter/public/unsubscribe?token={active.unsubscribe_token}"),
        client.get("/api/newsletter/public/confirm?token=xxxxxxxxxxxxxxxx"),
    ]
    for page in pages:
        assert back_link in page.text
        assert "Bülten'e dön" in page.text


def test_failed_resend_keeps_the_previous_link_working(client, auth_headers, db_session, test_user, monkeypatch):
    """Regression: resend rotated the token before sending, so a failed send killed the link
    already in the recipient's inbox."""
    sub = _subscription(db_session, test_user, email="colleague@example.com", status="pending")
    crud.update_newsletter_subscription(db_session, sub, confirm_sent_at=datetime.now(timezone.utc) - timedelta(hours=2))
    old_token = sub.confirm_token

    async def broken(mail):
        raise OSError("connection refused")

    monkeypatch.setattr(newsletter_service.email_service, "send_email", broken)
    response = client.post(f"/api/newsletter/subscriptions/{sub.id}/resend-confirmation", headers=auth_headers)
    assert response.status_code == 502

    done = client.post(f"/api/newsletter/public/confirm?token={old_token}")
    assert "onaylandı" in done.text


def test_resend_reuses_the_link_and_extends_it(client, auth_headers, db_session, test_user, outbox):
    sub = _subscription(db_session, test_user, email="colleague@example.com", status="pending")
    crud.update_newsletter_subscription(db_session, sub, confirm_sent_at=datetime.now(timezone.utc) - timedelta(days=6))
    token = sub.confirm_token
    assert client.post(f"/api/newsletter/subscriptions/{sub.id}/resend-confirmation",
                       headers=auth_headers).status_code == 200
    assert f"token={token}" in outbox[0].text
    db_session.expire_all()
    assert not newsletter_service.confirmation_expired(crud.get_newsletter_subscription(db_session, sub.id))


def test_old_subscription_back_in_pending_with_failed_mail_is_not_deleted(client, auth_headers, db_session,
                                                                         test_user, monkeypatch):
    """Regression: a subscription returning to "pending" whose confirmation mail failed was judged by
    its months-old created_at and deleted (with its history) by the next scheduler run."""
    sub = _subscription(db_session, test_user, email="colleague@example.com", status="unsubscribed")
    sub.created_at = NOW - timedelta(days=60)
    db_session.commit()
    crud.create_newsletter_delivery(db_session, sub.id, "sent")

    async def broken(mail):
        raise OSError("connection refused")

    monkeypatch.setattr(newsletter_service.email_service, "send_email", broken)
    response = client.post(f"/api/newsletter/subscriptions/{sub.id}/resume", headers=auth_headers)
    assert response.json()["status"] == "pending" and response.json()["confirm_sent_at"] is None

    asyncio.run(newsletter_service.send_due_newsletters(db_session, now=datetime.now(timezone.utc)))
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id) is not None
    assert len(crud.get_newsletter_deliveries(db_session, sub.id)) == 1


def test_expired_confirmation_link_is_rejected(client, db_session, test_user):
    sub = _subscription(db_session, test_user, email="colleague@example.com", status="pending")
    crud.update_newsletter_subscription(db_session, sub, confirm_sent_at=datetime.now(timezone.utc) - timedelta(days=8))
    response = client.post(f"/api/newsletter/public/confirm?token={sub.confirm_token}")
    assert "süresi dolmuş" in response.text
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).status == "pending"


def test_invalid_tokens(client):
    assert "geçersiz" in client.get("/api/newsletter/public/confirm?token=xxxxxxxxxxxxxxxx").text
    assert "geçersiz" in client.post("/api/newsletter/public/unsubscribe?token=xxxxxxxxxxxxxxxx").text
    assert client.get("/api/newsletter/public/unsubscribe").status_code == 422


def test_unsubscribe_get_does_not_unsubscribe_post_does(client, db_session, test_user):
    sub = _subscription(db_session, test_user)
    page = client.get(f"/api/newsletter/public/unsubscribe?token={sub.unsubscribe_token}")
    assert "Abonelikten çık" in page.text
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).status == "active"

    # RFC 8058 one-click: mail client POSTs a form body to the List-Unsubscribe URL.
    done = client.post(f"/api/newsletter/public/unsubscribe?token={sub.unsubscribe_token}",
                       content="List-Unsubscribe=One-Click",
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert done.status_code == 200
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).status == "unsubscribed"


def test_html_in_public_page_is_escaped(client, db_session, test_user):
    sub = _subscription(db_session, test_user, email="<script>x</script>@example.com")
    page = client.get(f"/api/newsletter/public/unsubscribe?token={sub.unsubscribe_token}")
    assert "<script>" not in page.text


# ==================== Scheduling ====================

def test_daily_slot_and_catch_up(db_session, test_user):
    sub = _subscription(db_session, test_user, send_hour=8)
    assert newsletter_service.latest_slot(sub, NOW) == datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
    assert newsletter_service.is_due(sub, NOW)
    # Still due when the server comes back within the catch-up window...
    assert newsletter_service.is_due(sub, NOW + timedelta(hours=5))
    # ...but not long after.
    assert not newsletter_service.is_due(sub, NOW + timedelta(hours=7))
    # Before today's slot the previous day's slot (long gone) is the latest one.
    assert not newsletter_service.is_due(sub, NOW - timedelta(hours=1))


def test_weekly_slot_only_on_its_weekday(db_session, test_user):
    friday = _subscription(db_session, test_user, frequency="weekly", send_weekday=4, send_hour=8)
    monday = _subscription(db_session, test_user, frequency="weekly", send_weekday=0, send_hour=8)
    assert newsletter_service.is_due(friday, NOW)
    assert not newsletter_service.is_due(monday, NOW)
    assert newsletter_service.latest_slot(monday, NOW) == datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)


def test_send_hour_follows_berlin_summer_and_winter_time(db_session, test_user):
    sub = _subscription(db_session, test_user, send_hour=8)
    winter = datetime(2027, 1, 15, 12, 0, tzinfo=timezone.utc)  # CET, UTC+1
    assert newsletter_service.latest_slot(sub, winter) == datetime(2027, 1, 15, 7, 0, tzinfo=timezone.utc)
    summer = datetime(2027, 7, 15, 12, 0, tzinfo=timezone.utc)  # CEST, UTC+2
    assert newsletter_service.latest_slot(sub, summer) == datetime(2027, 7, 15, 6, 0, tzinfo=timezone.utc)


def test_no_backfill_of_slot_before_activation(db_session, test_user):
    sub = _subscription(db_session, test_user, send_hour=8, active_since=NOW - timedelta(minutes=5))
    assert not newsletter_service.is_due(sub, NOW)


def test_same_slot_is_sent_only_once(db_session, test_user, outbox):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber", "high", 1))
    _subscription(db_session, test_user)
    assert _run(db_session) == 1
    assert _run(db_session, NOW + timedelta(minutes=30)) == 0
    assert len(outbox) == 1


def test_claim_is_atomic(db_session, test_user):
    sub = _subscription(db_session, test_user)
    slot = newsletter_service.latest_slot(sub, NOW)
    assert crud.claim_newsletter_slot(db_session, sub.id, slot) is True
    assert crud.claim_newsletter_slot(db_session, sub.id, slot) is False


def test_smtp_not_configured_skips_run_without_claiming(db_session, test_user, monkeypatch, outbox):
    _category(db_session, "AVRUPA")
    sub = _subscription(db_session, test_user)
    monkeypatch.setattr(app_settings, "smtp_host", "")
    assert _run(db_session) == 0
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).last_sent_at is None


def test_inactive_owner_and_paused_subscriptions_are_not_sent(db_session, test_user, outbox):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber", "high", 1))
    _subscription(db_session, test_user, status="paused")
    other = crud.create_user(db_session, email="gone@example.com", hashed_password=hash_password("x" * 10))
    _subscription(db_session, other)
    other.is_active = False
    db_session.commit()
    assert _run(db_session) == 0
    assert outbox == []


def test_expired_pending_subscriptions_are_cleaned_up(db_session, test_user):
    old = _subscription(db_session, test_user, email="a@example.com", status="pending")
    crud.update_newsletter_subscription(db_session, old, confirm_sent_at=NOW - timedelta(days=8))
    fresh = _subscription(db_session, test_user, email="b@example.com", status="pending")
    crud.update_newsletter_subscription(db_session, fresh, confirm_sent_at=NOW - timedelta(days=1))
    _run(db_session)
    remaining = {s.email for s in db_session.query(models.NewsletterSubscription).all()}
    assert remaining == {"b@example.com"}


# ==================== Building & delivering ====================

def test_same_filters_build_once_for_everyone(db_session, test_user, admin_user, outbox, bulletin_llm):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber 1", "high", 1), ("Haber 2", "med", 2))
    _subscription(db_session, test_user, delivery_format="email")
    _subscription(db_session, admin_user, delivery_format="docx")
    assert _run(db_session) == 2
    assert bulletin_llm["build"] == 1
    assert sorted(m.to for m in outbox) == ["admin@example.com", "tester@example.com"]
    statuses = [d.status for d in db_session.query(models.NewsletterDelivery).all()]
    assert statuses == ["sent", "sent"]


def test_different_filters_build_separately(db_session, test_user, outbox, bulletin_llm):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber 1", "high", 1))
    _subscription(db_session, test_user, max_articles=5)
    _subscription(db_session, test_user, max_articles=10)
    _run(db_session)
    assert bulletin_llm["build"] == 2


@pytest.mark.parametrize("fmt, attachment, content_in_body", [
    ("docx", True, False),
    ("email", False, True),
    ("both", True, True),
])
def test_delivery_formats(db_session, test_user, outbox, fmt, attachment, content_in_body):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Önemli Haber", "high", 1))
    _subscription(db_session, test_user, delivery_format=fmt)
    _run(db_session)
    mail = outbox[0]
    assert bool(mail.attachments) is attachment
    assert ("Önemli Haber özeti" in mail.html) is content_in_body
    assert mail.subject == "Günlük Bülten – 02.10.2026"
    assert mail.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "/api/newsletter/public/unsubscribe?token=" in mail.headers["List-Unsubscribe"]
    assert "Abonelikten çık" in mail.html and "Abonelikten çık" in mail.text
    if attachment:
        assert mail.attachments[0].filename == "bulten-gunluk-2026-10-02.docx"


def test_docx_attachment_carries_subscription_metadata(db_session, test_user, outbox):
    avrupa = _category(db_session, "AVRUPA")
    _category(db_session, "ASYA", 1)
    _articles(db_session, ("Haber", "high", 1))
    _subscription(db_session, test_user, delivery_format="docx", category_ids=[avrupa.id],
                  priorities=["high"], frequency="weekly", send_weekday=4)
    _run(db_session)
    props = DocxDocument(io.BytesIO(outbox[0].attachments[0].content)).core_properties
    assert props.author == "Bülten"
    assert props.title == "Haftalık Bülten – 02.10.2026"
    assert props.keywords == "AVRUPA"
    assert "Önem: Yüksek" in props.comments


def test_favorites_only_is_described_as_such(db_session, test_user, outbox):
    """Regression: priorities empty + Favoriler means ONLY favourites, but the metadata said "Tümü + Favoriler"."""
    _category(db_session, "AVRUPA")
    feed = _make_feed(db_session)
    _make_article(db_session, feed.id, title="Fav", priority="low", is_starred=True,
                  published_at=NOW - timedelta(hours=1))
    _subscription(db_session, test_user, delivery_format="docx", include_favorites=True)
    _run(db_session)
    props = DocxDocument(io.BytesIO(outbox[0].attachments[0].content)).core_properties
    assert "Önem: Yalnızca favoriler" in props.comments


def test_article_links_in_html_mail(db_session, test_user, outbox):
    _category(db_session, "AVRUPA")
    article = _articles(db_session, ("Haber", "high", 1))[0]
    _subscription(db_session, test_user, delivery_format="email")
    _run(db_session)
    assert f'href="{article.url}"' in outbox[0].html


def test_weekly_window_is_seven_days_daily_is_24_hours(db_session, test_user, outbox):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Dünkü", "high", 20), ("Üç gün önceki", "high", 72), ("Geçen ayki", "high", 24 * 30))
    _subscription(db_session, test_user, delivery_format="email")
    _subscription(db_session, test_user, delivery_format="email", frequency="weekly", send_weekday=4)
    _run(db_session)
    daily = next(m for m in outbox if m.subject.startswith("Günlük"))
    weekly = next(m for m in outbox if m.subject.startswith("Haftalık"))
    assert "Dünkü" in daily.html and "Üç gün önceki" not in daily.html
    assert "Dünkü" in weekly.html and "Üç gün önceki" in weekly.html and "Geçen ayki" not in weekly.html


def test_no_articles_sends_info_mail(db_session, test_user, outbox):
    _category(db_session, "AVRUPA")
    _subscription(db_session, test_user)
    _run(db_session)
    assert len(outbox) == 1
    assert outbox[0].subject.endswith("haber yok")
    assert outbox[0].attachments == []
    assert db_session.query(models.NewsletterDelivery).one().status == "skipped_no_articles"


def test_cost_limit_sends_info_mail(db_session, test_user, outbox, monkeypatch):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber", "high", 1))
    _subscription(db_session, test_user)

    async def over_limit(db, articles, categories):
        raise CostLimitExceededError("Daily cost limit exceeded")

    monkeypatch.setattr(bulletin_service, "build_bulletin_sections", over_limit)
    _run(db_session)
    assert "hazırlanamadı" in outbox[0].subject
    delivery = db_session.query(models.NewsletterDelivery).one()
    assert delivery.status == "skipped_cost_limit"


def test_no_categories_is_skipped_without_mail(db_session, test_user, outbox):
    _articles(db_session, ("Haber", "high", 1))
    _subscription(db_session, test_user)
    _run(db_session)
    assert outbox == []
    assert db_session.query(models.NewsletterDelivery).one().status == "skipped_no_categories"


def test_smtp_failure_retries_then_disables_after_three_failed_runs(db_session, test_user, monkeypatch):
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber", "high", 1))
    sub = _subscription(db_session, test_user)
    attempts = []

    async def broken(mail):
        attempts.append(mail)
        raise OSError("mailbox unavailable")

    monkeypatch.setattr(newsletter_service.email_service, "send_email", broken)
    for day in range(3):
        _run(db_session, NOW + timedelta(days=day))
    assert len(attempts) == 3 * newsletter_service.MAX_SEND_ATTEMPTS
    deliveries = crud.get_newsletter_deliveries(db_session, sub.id)
    assert [d.status for d in deliveries] == ["failed"] * 3
    assert deliveries[0].attempts == 3 and "mailbox unavailable" in deliveries[0].error
    db_session.expire_all()
    sub = crud.get_newsletter_subscription(db_session, sub.id)
    assert sub.status == "disabled" and sub.consecutive_failures == 3


def test_bulletin_build_errors_do_not_disable_the_subscription(db_session, test_user, monkeypatch, outbox):
    """Regression: an OpenAI outage counted as the subscriber's delivery failure and, after three
    runs, disabled every subscription with "check the address" advice."""
    _category(db_session, "AVRUPA")
    _articles(db_session, *[(f"Haber {day}", "high", 1 - 24 * day) for day in range(3)])  # one per run window
    sub = _subscription(db_session, test_user)

    async def outage(db, articles, categories):
        raise RuntimeError("OpenAI unavailable")

    monkeypatch.setattr(bulletin_service, "build_bulletin_sections", outage)
    for day in range(3):
        _run(db_session, NOW + timedelta(days=day))
    db_session.expire_all()
    sub = crud.get_newsletter_subscription(db_session, sub.id)
    assert sub.status == "active" and sub.consecutive_failures == 0
    deliveries = crud.get_newsletter_deliveries(db_session, sub.id)
    assert [d.status for d in deliveries] == ["skipped_build_error"] * 3
    assert "OpenAI unavailable" in deliveries[0].error
    assert outbox == []


def test_success_resets_failure_counter(db_session, test_user):
    _category(db_session, "AVRUPA")
    sub = _subscription(db_session, test_user)
    crud.update_newsletter_subscription(db_session, sub, consecutive_failures=2)
    _run(db_session)
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).consecutive_failures == 0


# ==================== Article selection ====================

def test_candidates_ordered_by_priority_then_recency(db_session):
    feed = _make_feed(db_session)
    def make(title, priority, hours):
        return _make_article(db_session, feed.id, title=title, priority=priority,
                             published_at=NOW - timedelta(hours=hours))
    make("low-new", "low", 1)
    make("high-old", "high", 20)
    make("med-new", "med", 2)
    make("high-new", "high", 3)
    rows = crud.get_bulletin_candidate_articles(db_session, start_date=NOW - timedelta(days=1), end_date=NOW,
                                                order_by_priority=True)
    assert [a.title for a in rows] == ["high-new", "high-old", "med-new", "low-new"]


def test_max_articles_is_an_upper_bound_by_priority(db_session, test_user):
    categories = [_category(db_session, "AVRUPA")]
    _articles(db_session, ("low", "low", 1), ("high", "high", 5), ("med", "med", 2))
    sub = _subscription(db_session, test_user, max_articles=2)
    chosen = asyncio.run(newsletter_service.select_articles(db_session, sub, categories, NOW - timedelta(days=1), NOW))
    assert [a.title for a in chosen] == ["high", "med"]
    sub.max_articles = 10
    chosen = asyncio.run(newsletter_service.select_articles(db_session, sub, categories, NOW - timedelta(days=1), NOW))
    assert len(chosen) == 3  # fewer than asked → all of them


def test_category_filter_keeps_only_subscribed_categories(db_session, test_user, outbox):
    avrupa = _category(db_session, "AVRUPA")
    asya = _category(db_session, "ASYA", 1)
    _articles(db_session, ("ASYA: Tokyo", "high", 1), ("Berlin", "high", 2))
    sub = _subscription(db_session, test_user, category_ids=[asya.id], delivery_format="email")
    chosen = asyncio.run(newsletter_service.select_articles(
        db_session, sub, [avrupa, asya], NOW - timedelta(days=1), NOW))
    assert [a.title for a in chosen] == ["ASYA: Tokyo"]


def test_category_filter_stops_classifying_once_enough_matched(db_session, test_user, bulletin_llm, monkeypatch):
    monkeypatch.setattr(app_settings, "bulletin_classification_batch_size", 2)
    avrupa = _category(db_session, "AVRUPA")
    _articles(db_session, *[(f"Haber {i}", "high", i + 1) for i in range(6)])
    sub = _subscription(db_session, test_user, category_ids=[avrupa.id], max_articles=2)
    asyncio.run(newsletter_service.select_articles(db_session, sub, [avrupa], NOW - timedelta(days=1), NOW))
    assert len(bulletin_llm["classified"]) == 2


def test_category_filter_classifies_with_brief_summaries(db_session, test_user, bulletin_llm):
    """Regression: classification for the category filter ran on title-only headers for articles
    without a brief summary, and that weaker result stayed cached for every later bulletin."""
    avrupa = _category(db_session, "AVRUPA")
    article = _articles(db_session, ("Berlin", "high", 1))[0]
    sub = _subscription(db_session, test_user, category_ids=[avrupa.id])
    asyncio.run(newsletter_service.select_articles(db_session, sub, [avrupa], NOW - timedelta(days=1), NOW))
    assert bulletin_llm["blocks"][article.id]["bullets"] == ["🔹 Berlin özeti."]


def test_deleted_category_drops_out_of_subscription(client, admin_headers, db_session, admin_user):
    avrupa = _category(db_session, "AVRUPA")
    asya = _category(db_session, "ASYA", 1)
    sub = _subscription(db_session, admin_user, category_ids=[avrupa.id, asya.id])
    assert client.delete(f"/api/bulletin/categories/{asya.id}", headers=admin_headers).status_code == 200
    db_session.expire_all()
    assert crud.get_newsletter_subscription(db_session, sub.id).category_ids == [avrupa.id]


# ==================== Şimdi gönder ====================

def test_send_now_runs_in_background_and_is_rate_limited(client, auth_headers, db_session, outbox):
    """Regression: building + mailing can outlast nginx's 120 s proxy timeout, so the request only
    queues the work (202) and the result shows up in the delivery history."""
    _category(db_session, "AVRUPA")
    _articles(db_session, ("Haber", "high", 1), now=datetime.now(timezone.utc))
    sub = _create(client, auth_headers).json()
    response = client.post(f"/api/newsletter/subscriptions/{sub['id']}/send-now", headers=auth_headers)
    assert response.status_code == 202, response.text
    assert response.json() == {"status": "queued"}
    assert len(outbox) == 1 and outbox[0].attachments

    again = client.post(f"/api/newsletter/subscriptions/{sub['id']}/send-now", headers=auth_headers)
    assert again.status_code == 429

    history = client.get(f"/api/newsletter/subscriptions/{sub['id']}/deliveries", headers=auth_headers).json()
    assert len(history) == 1
    assert history[0]["status"] == "sent" and history[0]["manual"] is True and history[0]["article_count"] == 1


def test_send_now_without_articles_does_not_burn_the_hourly_limit(client, auth_headers, db_session, outbox):
    """Regression: an empty period built no bulletin (no OpenAI cost) yet blocked "Şimdi gönder" for an hour."""
    _category(db_session, "AVRUPA")
    sub = _create(client, auth_headers).json()
    first = client.post(f"/api/newsletter/subscriptions/{sub['id']}/send-now", headers=auth_headers)
    assert first.status_code == 202
    assert outbox[0].subject.endswith("haber yok")

    _articles(db_session, ("Yeni haber", "high", 1), now=datetime.now(timezone.utc))
    second = client.post(f"/api/newsletter/subscriptions/{sub['id']}/send-now", headers=auth_headers)
    assert second.status_code == 202
    assert len(outbox) == 2 and outbox[1].attachments


def test_send_now_refuses_pending_and_unconfigured(client, auth_headers, monkeypatch, db_session, test_user):
    pending = _create(client, auth_headers, email="colleague@example.com").json()
    assert client.post(f"/api/newsletter/subscriptions/{pending['id']}/send-now",
                       headers=auth_headers).status_code == 400
    active = _create(client, auth_headers).json()
    monkeypatch.setattr(app_settings, "smtp_host", "")
    response = client.post(f"/api/newsletter/subscriptions/{active['id']}/send-now", headers=auth_headers)
    assert response.status_code == 400
    assert "yapılandırılmamış" in response.json()["detail"]
