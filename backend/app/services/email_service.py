"""
Outgoing e-mail over plain SMTP (stdlib only), for bulletin subscriptions.

Configured by the SMTP_* settings; while SMTP_HOST is empty `is_configured()` is False and
`send_email` raises `EmailNotConfiguredError` instead of trying to connect anywhere.
"""
import asyncio
import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_SMTP_TIMEOUT_SECONDS = 30


class EmailNotConfiguredError(RuntimeError):
    """SMTP_HOST is not set, so no mail can be sent."""


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    maintype: str = "application"
    subtype: str = "octet-stream"


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: Optional[str] = None
    attachments: List[EmailAttachment] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)


def is_configured() -> bool:
    return bool(settings.smtp_host.strip())


def sender_address() -> str:
    return settings.smtp_from.strip() or settings.smtp_username.strip()


def build_message(mail: OutgoingEmail) -> EmailMessage:
    """multipart/alternative (text + optional HTML) plus attachments."""
    msg = EmailMessage()
    msg["From"] = sender_address()
    msg["To"] = mail.to
    msg["Subject"] = mail.subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=(sender_address().rpartition("@")[2].strip("> ") or None))
    for name, value in mail.headers.items():
        msg[name] = value
    msg.set_content(mail.text)
    if mail.html:
        msg.add_alternative(mail.html, subtype="html")
    for attachment in mail.attachments:
        msg.add_attachment(
            attachment.content,
            maintype=attachment.maintype,
            subtype=attachment.subtype,
            filename=attachment.filename,
        )
    return msg


def _send_sync(msg: EmailMessage) -> None:
    host, port = settings.smtp_host.strip(), settings.smtp_port
    context = ssl.create_default_context()
    if port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=_SMTP_TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT_SECONDS)
    with server:
        if port != 465 and settings.smtp_use_tls:
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)


async def send_email(mail: OutgoingEmail) -> None:
    """Send one mail; the blocking SMTP conversation runs in a worker thread. Raises
    `EmailNotConfiguredError` when SMTP is not set up, and smtplib/OSError on failure."""
    if not is_configured():
        raise EmailNotConfiguredError("E-posta gönderimi yapılandırılmamış (SMTP_HOST boş)")
    msg = build_message(mail)
    await asyncio.to_thread(_send_sync, msg)
    logger.info("Mail sent: %s", mail.subject)
