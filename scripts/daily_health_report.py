#!/usr/bin/env python3
"""Sunucunun günlük sağlık raporunu Claude ile hazırlar.

.github/workflows/daily-health.yml tarafından her sabah çağrılır. Workflow sunucudan
SSH ile topladığı çıktıyı (docker compose ps, son 24 saatin hata logları, disk/bellek)
bir "bundle" dosyasına yazar; bu script:

  * bundle'daki secret'ları maskeler (API anahtarı, JWT, şifre, DB URL, e-posta),
  * Claude'a (Anthropic Messages API) analiz ettirir → önem derecesi OK / UYARI / KRITIK,
  * dış sağlık kontrolü veya SSH başarısızsa derece en az KRITIK olur (Claude ne derse desin),
  * Claude çağrısı başarısız olursa ham bulgularla yedek rapor üretir (bildirim kaybolmaz),
  * issue gövdesini (markdown) ve sonucu (JSON) yazar; GITHUB_OUTPUT varsa severity/title ekler.

Yalnızca standart kütüphane kullanır. Secret'ları asla stdout'a yazmaz.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-opus-5"
# Bundle'ın en yeni kısmı tutulur; kırpıldığında hem prompt'ta hem issue'da belirtilir.
MAX_BUNDLE_CHARS = 60_000
# GitHub issue/yorum gövdesi 65 536 karakterle sınırlı.
MAX_ISSUE_CHARS = 60_000

SEVERITIES = ("OK", "UYARI", "KRITIK")
SEVERITY_LABEL = {"OK": "✅ OK", "UYARI": "⚠️ UYARI", "KRITIK": "🔴 KRİTİK"}

_REDACTIONS = [
    # postgresql://user:pass@host → postgresql://***:***@host
    (re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s:/@]+:[^\s@]+@", re.I), r"\1***:***@"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "***JWT***"),
    (re.compile(r"(\bBearer\s+)[^\s'\"]+", re.I), r"\1***"),
    (
        re.compile(
            r"((?:password|passwd|pwd|secret|token|api[_-]?key|authorization)[\"']?\s*[=:]\s*[\"']?)[^\s\"',}]+",
            re.I,
        ),
        r"\1***",
    ),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "***@***"),
    # Repo public olabilir: sunucu ve ziyaretçi IP'leri issue'ya düşmesin.
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "x.x.x.x"),
]

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": {"type": "string", "enum": list(SEVERITIES)},
        "app_running": {"type": "boolean"},
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "evidence": {"type": "string"},
                    "likely_cause": {"type": "string"},
                    "action": {"type": "string"},
                },
                "required": ["problem", "evidence", "likely_cause", "action"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["severity", "app_running", "headline", "summary", "findings"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Sen "Bülten" uygulamasının nöbetçi SRE'sisin. Uygulama tek bir Linux sunucusunda
docker compose ile çalışır: `db` (PostgreSQL 16), `backend` (FastAPI + LangGraph + OpenAI; DW RSS
beslemelerini çeker, makaleleri özetler), `frontend` (nginx; /api isteklerini backend'e iletir).

Sana her sabah son 24 saatin verisi gelir. Görevin:
- Uygulama çalışıyor mu, kullanıcıyı etkileyen bir hata var mı, belirle.
- Tekrarlayan hataları grupla; aynı hatayı tekrar tekrar listeleme, kaç kez görüldüğünü söyle.
- Geçici/zararsız gürültüyü (tek seferlik ağ zaman aşımı, bot taramaları, 404'ler) ciddi hatalardan ayır.
- Disk > %85, bellek baskısı, container restart'ları gibi kaynak sorunlarını da değerlendir.

Önem derecesi:
- OK: kullanıcıyı etkileyen sorun yok (zararsız gürültü olabilir).
- UYARI: dikkat gerektiren ama uygulamayı durdurmayan sorun (tekrarlayan hata, dolmaya yakın disk, başarısız beslemeler).
- KRITIK: uygulama/servis çalışmıyor, sağlık kontrolü başarısız, sunucuya erişilemiyor, veri kaybı riski.

Tüm metinleri Türkçe yaz. `headline` 60 karakteri geçmesin (issue başlığı olacak). `evidence` alanında
ilgili log satırını kısaca alıntıla. `action` somut olsun (komut, dosya ya da kontrol edilecek yer).
Veride olmayan bir şeyi uydurma; emin değilsen bunu belirt."""


def redact(text: str) -> str:
    """Log metnindeki secret'ları `***` ile değiştirir."""
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def trim_bundle(text: str, limit: int = MAX_BUNDLE_CHARS) -> tuple:
    """(metin, kırpıldı_mı). Sınır aşılırsa en yeni (son) kısım tutulur."""
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def severity_floor(health_status: str, ssh_ok: bool) -> str:
    """Dış kontrollere göre en düşük önem derecesi — Claude bunun altına indiremez."""
    if not ssh_ok or health_status.strip() != "200":
        return "KRITIK"
    return "OK"


def max_severity(a: str, b: str) -> str:
    return a if SEVERITIES.index(a) >= SEVERITIES.index(b) else b


def build_prompt(bundle: str, health_status: str, ssh_ok: bool, truncated: bool) -> str:
    facts = [
        f"- Dış sağlık kontrolü (GET /api/health): HTTP {health_status or 'yanıt yok'}"
        + (" ✓" if health_status.strip() == "200" else " ✗ BAŞARISIZ"),
        f"- SSH ile sunucuya erişim: {'başarılı' if ssh_ok else 'BAŞARISIZ — sunucuya erişilemedi'}",
    ]
    if truncated:
        facts.append(f"- Not: toplanan veri {MAX_BUNDLE_CHARS} karakteri aştığı için yalnızca en yeni kısmı aşağıda.")
    body = bundle.strip() or "(sunucudan veri toplanamadı)"
    return "Kontrol sonuçları:\n" + "\n".join(facts) + "\n\nSunucudan toplanan veri:\n<bundle>\n" + body + "\n</bundle>"


def _post(url: str, headers: Dict[str, str], payload: dict, timeout: int = 300) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_claude(prompt: str, api_key: str, model: str = DEFAULT_MODEL, post: Optional[Callable] = None) -> dict:
    """Claude'dan ANALYSIS_SCHEMA biçiminde analiz ister. Hata durumunda RuntimeError."""
    post = post or _post
    headers = {
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        # Güvenlik sınıflandırıcısı isteği reddederse API aynı istek içinde uygun modele düşer.
        "anthropic-beta": "server-side-fallback-2026-07-01",
    }
    payload = {
        "model": model,
        "max_tokens": 16000,
        "fallbacks": "default",
        "system": SYSTEM_PROMPT,
        "output_config": {"format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}},
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        data = post(API_URL, headers, payload)
    except urllib.error.HTTPError as exc:
        # Gövde API hata mesajıdır; anahtarı içermez.
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Claude API HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Claude API'ye bağlanılamadı: {exc}") from None

    stop = data.get("stop_reason")
    if stop in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude yanıtı tamamlanmadı (stop_reason={stop})")
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    try:
        analysis = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("Claude yanıtı JSON olarak çözümlenemedi") from None
    if analysis.get("severity") not in SEVERITIES:
        raise RuntimeError("Claude yanıtında geçerli bir severity yok")
    return analysis


def fallback_analysis(health_status: str, ssh_ok: bool, error: str) -> dict:
    """Claude'a ulaşılamadığında kullanılan, yalnızca dış kontrollere dayanan analiz."""
    problems = []
    if not ssh_ok:
        problems.append("Sunucuya SSH ile erişilemedi")
    if health_status.strip() != "200":
        problems.append(f"/api/health HTTP {health_status or 'yanıt yok'} döndü")
    headline = "; ".join(problems) if problems else "Claude analizi yapılamadı"
    return {
        "severity": max_severity(severity_floor(health_status, ssh_ok), "UYARI"),
        "app_running": health_status.strip() == "200",
        "headline": headline[:60],
        "summary": f"Claude analizi yapılamadı ({error}). Aşağıdaki ham bulguları elle inceleyin.",
        "findings": [],
    }


def analyze(bundle_raw: str, health_status: str, ssh_ok: bool, api_key: str, model: str, post=None) -> dict:
    """Maskele → kırp → Claude → önem derecesini dış kontrollerle birleştir."""
    bundle, truncated = trim_bundle(redact(bundle_raw))
    floor = severity_floor(health_status, ssh_ok)
    if not api_key:
        analysis = fallback_analysis(health_status, ssh_ok, "ANTHROPIC_API_KEY tanımlı değil")
    else:
        try:
            analysis = call_claude(build_prompt(bundle, health_status, ssh_ok, truncated), api_key, model, post)
        except RuntimeError as exc:
            analysis = fallback_analysis(health_status, ssh_ok, redact(str(exc)))
    analysis["severity"] = max_severity(analysis["severity"], floor)
    analysis["bundle"] = bundle
    analysis["truncated"] = truncated
    analysis["health_status"] = health_status
    analysis["ssh_ok"] = ssh_ok
    return analysis


def issue_title(analysis: dict, today: str) -> str:
    label = "KRİTİK" if analysis["severity"] == "KRITIK" else analysis["severity"]
    return f"[Sağlık] {today} – {label}: {analysis['headline']}"


def render_issue(analysis: dict, today: str) -> str:
    lines = [
        f"## {SEVERITY_LABEL[analysis['severity']]} — Günlük sağlık raporu ({today})",
        "",
        f"- **/api/health:** HTTP {analysis['health_status'] or 'yanıt yok'}",
        f"- **SSH erişimi:** {'✓' if analysis['ssh_ok'] else '✗ erişilemedi'}",
        f"- **Uygulama çalışıyor mu:** {'evet' if analysis.get('app_running') else 'HAYIR'}",
        "",
        "### Özet",
        analysis["summary"],
    ]
    if analysis["findings"]:
        lines += ["", "### Bulgular"]
        for i, f in enumerate(analysis["findings"], 1):
            evidence = f["evidence"].replace("`", "'")
            lines += [
                "",
                f"**{i}. {f['problem']}**",
                f"- Kanıt: `{evidence}`",
                f"- Olası neden: {f['likely_cause']}",
                f"- Öneri: {f['action']}",
            ]
    body_head = "\n".join(lines)
    bundle = analysis["bundle"].strip() or "(veri yok)"
    note = " (yalnızca en yeni kısım)" if analysis["truncated"] else ""
    tail = "\n\n_Otomatik rapor: `.github/workflows/daily-health.yml` · loglar maskelenmiştir._"
    room = MAX_ISSUE_CHARS - len(body_head) - len(tail) - 200
    if len(bundle) > room:
        bundle, note = bundle[-max(room, 0):], " (yalnızca en yeni kısım)"
    details = f"\n\n<details><summary>Ham veri{note}</summary>\n\n```text\n{bundle}\n```\n</details>"
    return body_head + details + tail


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", required=True, help="Sunucudan toplanan çıktı dosyası (olmayabilir)")
    parser.add_argument("--health-status", default="", help="/api/health HTTP kodu (yanıt yoksa boş veya 000)")
    parser.add_argument("--ssh-ok", choices=("0", "1"), required=True)
    parser.add_argument("--out-md", required=True, help="Issue gövdesinin yazılacağı dosya")
    parser.add_argument("--out-json", required=True, help="Analiz sonucunun yazılacağı dosya")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    bundle_raw = bundle_path.read_text(encoding="utf-8", errors="replace") if bundle_path.exists() else ""
    analysis = analyze(
        bundle_raw,
        args.health_status,
        args.ssh_ok == "1",
        os.environ.get("ANTHROPIC_API_KEY", ""),
        os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL,
    )
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # Claude'un ürettiği metin de yayınlanmadan önce bir kez daha maskelenir.
    title = redact(issue_title(analysis, today))
    Path(args.out_md).write_text(redact(render_issue(analysis, today)), encoding="utf-8")
    Path(args.out_json).write_text(
        json.dumps({k: v for k, v in analysis.items() if k != "bundle"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"severity={analysis['severity']}\n")
            fh.write(f"title={title.replace(chr(10), ' ')}\n")
    print(f"[✓] Önem derecesi: {analysis['severity']} — {analysis['headline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
