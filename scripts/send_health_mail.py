#!/usr/bin/env python3
"""Uygulama çalışmadığında (ve tekrar ayağa kalktığında) e-posta bildirimi gönderir.

.github/workflows/daily-health.yml tarafından çağrılır:

  * `--kind down`: /api/health başarısız → daily_health_report.py'nin yazdığı analiz (report.json)
    özet, bulgular ve önerilerle mail olarak gönderilir;
  * `--kind recovered`: kesintiden sonra /api/health yeniden 200 → kısa "tekrar ayakta" maili.

SMTP ayarları backend ile aynı adlardadır (SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD,
SMTP_FROM, SMTP_USE_TLS); alıcı HEALTH_ALERT_EMAIL (virgülle birden fazla adres). Ayar eksikse veya
gönderim başarısızsa çıkış kodu 1 olur — bildirimin gitmediği Actions'ta kırmızı görünsün diye.

Yalnızca standart kütüphane kullanır. Secret'ları asla stdout'a yazmaz.
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from typing import Callable, Dict, List, Optional

SMTP_TIMEOUT_SECONDS = 30
SEVERITY_TEXT = {"OK": "OK", "UYARI": "UYARI", "KRITIK": "KRİTİK"}


def recipients(raw: str) -> List[str]:
    return [a.strip() for a in raw.split(",") if a.strip()]


def build_down_mail(analysis: dict, link: str) -> tuple:
    """(konu, gövde) — uygulama çalışmıyor bildirimi."""
    subject = f"[Bülten] Uygulama çalışmıyor: {analysis.get('headline', '').strip() or 'sağlık kontrolü başarısız'}"
    lines = [
        "Bülten uygulaması dışarıdan yapılan sağlık kontrolünde yanıt vermedi.",
        "",
        f"/api/health : HTTP {analysis.get('health_status') or 'yanıt yok'}",
        f"SSH erişimi : {'başarılı' if analysis.get('ssh_ok') else 'BAŞARISIZ — sunucuya erişilemedi'}",
        f"Önem        : {SEVERITY_TEXT.get(analysis.get('severity', ''), analysis.get('severity', '?'))}",
        "",
        "ÖZET (Claude log analizi)",
        analysis.get("summary", "").strip() or "-",
    ]
    for i, f in enumerate(analysis.get("findings") or [], 1):
        lines += [
            "",
            f"{i}. {f.get('problem', '')}",
            f"   Kanıt      : {f.get('evidence', '')}",
            f"   Olası neden: {f.get('likely_cause', '')}",
            f"   Öneri      : {f.get('action', '')}",
        ]
    if link:
        lines += ["", f"Ayrıntılar ve ham loglar: {link}"]
    lines += ["", "Aynı kesinti için tekrar mail gönderilmez; uygulama tekrar ayağa kalkınca ayrıca bildirilir.",
              "-- Daily Health (.github/workflows/daily-health.yml)"]
    return subject, "\n".join(lines)


def build_recovered_mail(health_status: str, link: str) -> tuple:
    """(konu, gövde) — kesinti bitti bildirimi."""
    subject = "[Bülten] Uygulama tekrar çalışıyor"
    lines = [
        f"Bülten uygulaması sağlık kontrolüne yeniden yanıt veriyor (/api/health → HTTP {health_status or '200'}).",
    ]
    if link:
        lines += ["", f"Kesinti kaydı: {link}"]
    lines += ["", "-- Daily Health (.github/workflows/daily-health.yml)"]
    return subject, "\n".join(lines)


def build_message(subject: str, body: str, sender: str, to: List[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=(sender.rpartition("@")[2].strip("> ") or None))
    msg.set_content(body)
    return msg


def send(msg: EmailMessage, env: Dict[str, str], smtp_factory: Optional[Callable] = None) -> None:
    """Backend'deki email_service ile aynı kural: 465 → SSL, diğer portlarda SMTP_USE_TLS ise STARTTLS."""
    host = env.get("SMTP_HOST", "").strip()
    port = int(env.get("SMTP_PORT") or 587)
    use_tls = env.get("SMTP_USE_TLS", "true").strip().lower() not in ("0", "false", "no")
    context = ssl.create_default_context()
    if smtp_factory:
        server = smtp_factory(host, port)
    elif port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SECONDS)
    with server:
        if port != 465 and use_tls:
            server.starttls(context=context)
        if env.get("SMTP_USERNAME"):
            server.login(env["SMTP_USERNAME"], env.get("SMTP_PASSWORD", ""))
        server.send_message(msg)


def main(argv: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None, smtp_factory=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kind", choices=("down", "recovered"), required=True)
    parser.add_argument("--report", help="daily_health_report.py'nin --out-json çıktısı (--kind down için)")
    parser.add_argument("--health-status", default="", help="/api/health HTTP kodu (--kind recovered için)")
    parser.add_argument("--link", default="", help="Mailde verilecek issue / Actions çalışması adresi")
    args = parser.parse_args(argv)
    env = dict(os.environ) if env is None else env

    to = recipients(env.get("HEALTH_ALERT_EMAIL", ""))
    if not to:
        print("[✗] HEALTH_ALERT_EMAIL tanımlı değil — bildirim maili gönderilemedi.")
        return 1
    if not env.get("SMTP_HOST", "").strip():
        print("[✗] SMTP_HOST tanımlı değil — bildirim maili gönderilemedi.")
        return 1
    sender = env.get("SMTP_FROM", "").strip() or env.get("SMTP_USERNAME", "").strip()
    if not sender:
        print("[✗] SMTP_FROM / SMTP_USERNAME tanımlı değil — gönderen adres yok.")
        return 1

    if args.kind == "down":
        report_path = Path(args.report or "")
        analysis = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        subject, body = build_down_mail(analysis, args.link)
    else:
        subject, body = build_recovered_mail(args.health_status, args.link)

    try:
        send(build_message(subject, body, sender, to), env, smtp_factory)
    except (smtplib.SMTPException, OSError) as exc:
        # smtplib hataları sunucu yanıtını içerir, şifreyi içermez.
        print(f"[✗] Mail gönderilemedi: {type(exc).__name__}: {exc}")
        return 1
    print(f"[✓] Bildirim maili gönderildi ({args.kind}, {len(to)} alıcı).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
