"""scripts/send_health_mail.py — uygulama çalışmadığında / tekrar ayağa kalktığında e-posta bildirimi."""
import importlib.util
import json
import smtplib
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "send_health_mail.py"
_spec = importlib.util.spec_from_file_location("send_health_mail", _SCRIPT)
mail = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mail)

ENV = {
    "HEALTH_ALERT_EMAIL": "ops@example.com, ben@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": "587",
    "SMTP_USERNAME": "bot@example.com",
    "SMTP_PASSWORD": "Gizli123",
    "SMTP_FROM": "Bülten <bot@example.com>",
}

ANALYSIS = {
    "severity": "KRITIK",
    "app_running": False,
    "headline": "Backend container durmuş",
    "summary": "backend OOM ile öldü, nginx 502 dönüyor.",
    "findings": [
        {
            "problem": "Backend OOM",
            "evidence": "backend-1 exited (137) oom=true",
            "likely_cause": "Bellek yetersiz",
            "action": "docker compose up -d backend",
        }
    ],
    "health_status": "502",
    "ssh_ok": True,
}


class FakeSMTP:
    instances = []

    def __init__(self, host, port):
        self.host, self.port = host, port
        self.calls, self.sent = [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user))

    def send_message(self, msg):
        self.sent.append(msg)


def _report(tmp_path, analysis=ANALYSIS):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
    return path


def test_down_mail_contains_log_analysis(tmp_path):
    FakeSMTP.instances.clear()
    argv = ["--kind", "down", "--report", str(_report(tmp_path)), "--link", "https://github.com/x/y/issues/5"]
    assert mail.main(argv, env=ENV, smtp_factory=FakeSMTP) == 0
    server = FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.calls == ["starttls", ("login", "bot@example.com")]
    msg = server.sent[0]
    assert msg["To"] == "ops@example.com, ben@example.com"
    assert "Uygulama çalışmıyor" in msg["Subject"]
    assert "Backend container durmuş" in msg["Subject"]
    body = msg.get_content()
    for text in ("HTTP 502", "backend OOM ile öldü", "Backend OOM", "docker compose up -d backend",
                 "https://github.com/x/y/issues/5"):
        assert text in body


def test_down_mail_without_report_still_sends(tmp_path):
    # Analiz dosyası yoksa bile bildirim kaybolmamalı.
    FakeSMTP.instances.clear()
    argv = ["--kind", "down", "--report", str(tmp_path / "yok.json")]
    assert mail.main(argv, env=ENV, smtp_factory=FakeSMTP) == 0
    assert FakeSMTP.instances[0].sent


def test_recovered_mail():
    FakeSMTP.instances.clear()
    assert mail.main(["--kind", "recovered", "--health-status", "200"], env=ENV, smtp_factory=FakeSMTP) == 0
    msg = FakeSMTP.instances[0].sent[0]
    assert "tekrar çalışıyor" in msg["Subject"]
    assert "HTTP 200" in msg.get_content()


def test_missing_recipient_or_smtp_fails_loudly(tmp_path, capsys):
    argv = ["--kind", "down", "--report", str(_report(tmp_path))]
    assert mail.main(argv, env={**ENV, "HEALTH_ALERT_EMAIL": ""}, smtp_factory=FakeSMTP) == 1
    assert "HEALTH_ALERT_EMAIL" in capsys.readouterr().out
    assert mail.main(argv, env={**ENV, "SMTP_HOST": ""}, smtp_factory=FakeSMTP) == 1
    assert "SMTP_HOST" in capsys.readouterr().out


def test_smtp_error_returns_1_without_leaking_password(tmp_path, capsys):
    class Failing(FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")

    argv = ["--kind", "down", "--report", str(_report(tmp_path))]
    assert mail.main(argv, env=ENV, smtp_factory=Failing) == 1
    out = capsys.readouterr().out
    assert "Mail gönderilemedi" in out
    assert "Gizli123" not in out


def test_port_465_skips_starttls_and_tls_can_be_disabled():
    FakeSMTP.instances.clear()
    mail.main(["--kind", "recovered"], env={**ENV, "SMTP_PORT": "465"}, smtp_factory=FakeSMTP)
    mail.main(["--kind", "recovered"], env={**ENV, "SMTP_USE_TLS": "false"}, smtp_factory=FakeSMTP)
    assert len(FakeSMTP.instances) == 2
    assert all("starttls" not in s.calls for s in FakeSMTP.instances)


def test_empty_port_variable_defaults_to_587():
    # Workflow'da vars.SMTP_PORT tanımlı değilse boş string gelir.
    FakeSMTP.instances.clear()
    mail.main(["--kind", "recovered"], env={**ENV, "SMTP_PORT": ""}, smtp_factory=FakeSMTP)
    assert FakeSMTP.instances[0].port == 587
