#!/usr/bin/env python3
"""Daily Health workflow'unun bu çalışmada ne yapacağına karar verir.

.github/workflows/daily-health.yml sık bir zamanlama kullanır (10 dakikada bir), çünkü GitHub
zamanlanmış çalışmaları çok düzensiz tetikler; günde tek raporu bu kapı sağlar. Kural:

  * elle başlatılan çalışma (workflow_dispatch) her zaman çalışır;
  * zamanlanmış çalışma, Berlin saatiyle 08:00 olmadıysa çalışmaz;
  * 08:00'den sonraysa, bugün (Berlin tarihi) raporu teslim etmiş başka bir zamanlanmış çalışma
    yoksa çalışır — 08:00'den sonra gelen ilk çalışma raporu üretir, sonrakiler atlanır.

"Raporu teslim etmiş" = workflow'daki REPORT_STEP adımı 08:00'den sonra başarıyla bitmiş. Kapıda
duran çalışmalarda rapor job'u atlanır (adımı yoktur), başarısız olanlarda adım `failure` — ikisi de
sayılmaz. 08:00'den önceki kesinti raporları da günlük rapor yerine geçmez.

Ayrıca her çalışmada uygulamanın ayakta olup olmadığına bakılır (workflow'un ölçtüğü /api/health kodu,
HEALTH_STATUS ortam değişkeni) ve açık bir kesinti kaydı (OUTAGE_LABEL etiketli açık issue) ile
karşılaştırılır:

  * uygulama çalışmıyor ve kayıt yok → `alert`: saatten bağımsız log analizi + e-posta bildirimi;
  * uygulama yeniden 200 dönüyor ve kayıt açık → `recover`: "tekrar ayakta" e-postası;
  * diğer durumlarda bildirim yok (aynı kesinti için 10 dakikada bir mail gitmez).

Yalnızca standart kütüphane ve `gh` CLI kullanır; sonucu GITHUB_OUTPUT'a `run`, `alert`, `recover`
(true|false) olarak yazar.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
REPORT_HOUR = 8
WORKFLOW_FILE = "daily-health.yml"
# daily-health.yml'deki son adımın adı — değişirse burayı da güncelleyin (test kontrol eder).
REPORT_STEP = "Issue aç / güncelle / kapat"
# Bildirimi gönderilmiş, henüz bitmemiş kesintiyi işaretleyen issue etiketi.
OUTAGE_LABEL = "app-down"


def should_run(event_name: str, now_utc: datetime, reported: List[datetime]) -> tuple:
    """(çalışsın_mı, gerekçe)."""
    if event_name != "schedule":
        return True, f"{event_name} → her zaman çalışır"
    now = now_utc.astimezone(BERLIN)
    if now.hour < REPORT_HOUR:
        return False, f"Berlin {now:%H:%M} — henüz {REPORT_HOUR:02d}:00 olmadı"
    today = now.date()
    done = [
        r for r in reported
        if r.astimezone(BERLIN).date() == today and r.astimezone(BERLIN).hour >= REPORT_HOUR
    ]
    if done:
        return False, f"bugünkü rapor zaten {done[0].astimezone(BERLIN):%H:%M}'de gönderildi"
    return True, f"Berlin {now:%H:%M} — bugün henüz rapor yok"


def outage_action(health_status: str, outage_open: bool) -> Optional[str]:
    """"alert" (yeni kesinti), "recover" (kesinti bitti) ya da None."""
    app_up = health_status.strip() == "200"
    if not app_up and not outage_open:
        return "alert"
    if app_up and outage_open:
        return "recover"
    return None


def _gh(args: List[str]) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def _parse_ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def reported_runs(gh: Callable[[List[str]], str], current_run_id: str) -> List[datetime]:
    """Raporu teslim etmiş zamanlanmış çalışmaların oluşturulma zamanları (son birkaç gün)."""
    runs = json.loads(
        gh(["run", "list", "--workflow", WORKFLOW_FILE, "--event", "schedule", "--limit", "10",
            "--json", "databaseId,createdAt"])
    )
    reported = []
    for run in runs:
        run_id = str(run["databaseId"])
        if run_id == str(current_run_id):
            continue
        view = json.loads(gh(["run", "view", run_id, "--json", "jobs"]))
        steps = [s for job in view.get("jobs", []) for s in job.get("steps", [])]
        if any(s.get("name") == REPORT_STEP and s.get("conclusion") == "success" for s in steps):
            reported.append(_parse_ts(run["createdAt"]))
    return reported


def outage_open(gh: Callable[[List[str]], str]) -> bool:
    """OUTAGE_LABEL etiketli açık bir issue var mı (= bu kesinti için bildirim zaten gitti mi)."""
    issues = json.loads(
        gh(["issue", "list", "--label", OUTAGE_LABEL, "--state", "open", "--limit", "1", "--json", "number"])
    )
    return bool(issues)


def main(gh: Optional[Callable[[List[str]], str]] = None) -> int:
    gh = gh or _gh
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    health_status = os.environ.get("HEALTH_STATUS", "")
    now = datetime.now(timezone.utc)
    reported: List[datetime] = []
    if event == "schedule" and now.astimezone(BERLIN).hour >= REPORT_HOUR:
        try:
            reported = reported_runs(gh, os.environ.get("GITHUB_RUN_ID", ""))
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
            # Geçmiş okunamazsa çalışmayı tercih et: fazladan bir yorum, kaçan rapordan iyidir.
            print(f"[!] Önceki çalışmalar okunamadı ({exc}); rapor yine de üretilecek.")
    run, reason = should_run(event, now, reported)
    try:
        is_open = outage_open(gh)
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        # Kayıt okunamazsa "açık değil" say: çift bildirim, kaçan kesinti bildiriminden iyidir.
        print(f"[!] Kesinti kaydı okunamadı ({exc}); açık değil sayılıyor.")
        is_open = False
    action = outage_action(health_status, is_open)
    outputs = {"run": run or action == "alert", "alert": action == "alert", "recover": action == "recover"}
    print(f"/api/health → HTTP {health_status or 'yanıt yok'}, açık kesinti kaydı: {'var' if is_open else 'yok'}")
    print(" ".join(f"{k}={str(v).lower()}" for k, v in outputs.items()) + f" — {reason}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            for key, value in outputs.items():
                fh.write(f"{key}={str(value).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
