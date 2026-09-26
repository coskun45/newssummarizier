"""scripts/daily_health_report.py — günlük sunucu sağlık raporunu Claude ile hazırlayan script."""
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "daily_health_report.py"
_spec = importlib.util.spec_from_file_location("daily_health_report", _SCRIPT)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

BUNDLE = """=== docker compose ps -a ===
backend  Up 2 hours (healthy)
=== hata logları ===
backend-1 | 2026-09-26T03:00:01Z ERROR openai call failed api_key=sk-proj-abcdefghijklmnop1234
backend-1 | DATABASE_URL=postgresql+psycopg2://bulten:SuperGizli123@db:5432/bulten
backend-1 | Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl
backend-1 | login failed for admin@example.com password=hunter2 from 77.42.89.136
"""


def _claude_response(analysis: dict, stop_reason: str = "end_turn") -> dict:
    return {"stop_reason": stop_reason, "content": [{"type": "text", "text": json.dumps(analysis)}]}


def _analysis(severity: str = "OK") -> dict:
    return {
        "severity": severity,
        "app_running": True,
        "headline": "Sorun yok",
        "summary": "Her şey yolunda.",
        "findings": [],
    }


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, payload):
        self.calls.append((url, headers, payload))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_redact_removes_secrets_and_ips():
    out = report.redact(BUNDLE)
    for secret in ("sk-proj-abcdefghijklmnop1234", "SuperGizli123", "eyJhbGciOiJIUzI1NiJ9", "hunter2",
                   "admin@example.com", "77.42.89.136"):
        assert secret not in out
    assert "ERROR openai call failed" in out  # log anlamı korunur


def test_secrets_never_reach_claude_or_issue():
    rec = _Recorder(_claude_response(_analysis("UYARI")))
    result = report.analyze(BUNDLE, "200", True, "test-key", "claude-opus-5", post=rec)
    sent = json.dumps(rec.calls[0][2])
    issue = report.render_issue(result, "2026-09-26")
    for secret in ("SuperGizli123", "hunter2", "sk-proj-abcdefghijklmnop1234", "77.42.89.136"):
        assert secret not in sent
        assert secret not in issue


def test_request_shape():
    rec = _Recorder(_claude_response(_analysis()))
    report.analyze("log", "200", True, "test-key", "claude-opus-5", post=rec)
    url, headers, payload = rec.calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-opus-5"
    assert payload["output_config"]["format"]["type"] == "json_schema"


def test_health_failure_forces_kritik_even_if_claude_says_ok():
    rec = _Recorder(_claude_response(_analysis("OK")))
    result = report.analyze("log", "502", True, "k", "m", post=rec)
    assert result["severity"] == "KRITIK"


def test_ssh_failure_forces_kritik():
    rec = _Recorder(_claude_response(_analysis("OK")))
    result = report.analyze("", "200", False, "k", "m", post=rec)
    assert result["severity"] == "KRITIK"
    assert "BAŞARISIZ" in rec.calls[0][2]["messages"][0]["content"]


def test_claude_severity_kept_when_checks_pass():
    rec = _Recorder(_claude_response(_analysis("UYARI")))
    assert report.analyze("log", "200", True, "k", "m", post=rec)["severity"] == "UYARI"


def test_claude_http_error_falls_back_to_report():
    err = urllib.error.HTTPError(report.API_URL, 529, "Overloaded", {}, io.BytesIO(b'{"error":"overloaded"}'))
    result = report.analyze("log", "200", True, "k", "m", post=_Recorder(err))
    assert result["severity"] == "UYARI"  # bildirim kaybolmaz
    assert "Claude analizi yapılamadı" in result["summary"]


def test_claude_error_with_down_app_is_kritik():
    result = report.analyze("", "000", False, "k", "m", post=_Recorder(urllib.error.URLError("dns")))
    assert result["severity"] == "KRITIK"
    assert "SSH" in result["headline"]


def test_refusal_and_bad_json_fall_back():
    refused = report.analyze("log", "200", True, "k", "m", post=_Recorder(_claude_response(_analysis(), "refusal")))
    assert "Claude analizi yapılamadı" in refused["summary"]
    bad = {"stop_reason": "end_turn", "content": [{"type": "text", "text": "not json"}]}
    assert "Claude analizi yapılamadı" in report.analyze("log", "200", True, "k", "m", post=_Recorder(bad))["summary"]


def test_missing_api_key_does_not_call_claude():
    rec = _Recorder(_claude_response(_analysis()))
    result = report.analyze("log", "200", True, "", "m", post=rec)
    assert rec.calls == []
    assert result["severity"] == "UYARI"


def test_large_bundle_keeps_newest_part_and_says_so():
    big = "eski\n" * 20_000 + "EN_YENI_SATIR"
    rec = _Recorder(_claude_response(_analysis()))
    result = report.analyze(big, "200", True, "k", "m", post=rec)
    prompt = rec.calls[0][2]["messages"][0]["content"]
    assert result["truncated"] is True
    assert "EN_YENI_SATIR" in prompt
    assert "yalnızca en yeni kısmı" in prompt


def test_issue_body_fits_github_limit():
    rec = _Recorder(_claude_response(_analysis("UYARI")))
    result = report.analyze("x" * 200_000, "200", True, "k", "m", post=rec)
    assert len(report.render_issue(result, "2026-09-26")) < 65_536


def test_title_and_findings_render():
    analysis = _analysis("KRITIK")
    analysis["headline"] = "backend çalışmıyor"
    analysis["findings"] = [{"problem": "DB bağlantısı", "evidence": "could not connect", "likely_cause": "db düştü",
                             "action": "docker compose restart db"}]
    rec = _Recorder(_claude_response(analysis))
    result = report.analyze("log", "200", True, "k", "m", post=rec)
    assert report.issue_title(result, "2026-09-27") == "[Sağlık] 2026-09-27 – KRİTİK: backend çalışmıyor"
    body = report.render_issue(result, "2026-09-27")
    assert "docker compose restart db" in body
    assert "<details>" in body


def test_main_writes_outputs(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle.txt"
    bundle.write_text("log", encoding="utf-8")
    gh_out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["x", "--bundle", str(bundle), "--health-status", "000", "--ssh-ok", "0",
                                     "--out-md", str(tmp_path / "i.md"), "--out-json", str(tmp_path / "r.json")])
    assert report.main() == 0
    assert "severity=KRITIK" in gh_out.read_text(encoding="utf-8")
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["severity"] == "KRITIK"
    assert (tmp_path / "i.md").read_text(encoding="utf-8").startswith("## 🔴 KRİTİK")
