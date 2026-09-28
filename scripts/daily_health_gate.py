#!/usr/bin/env python3
"""Daily Health workflow'unun bu çalışmada rapor üretip üretmeyeceğine karar verir.

.github/workflows/daily-health.yml iki zamanlama kullanır (06:23 ve 07:23 UTC), çünkü GitHub cron
yalnızca UTC bilir ve zamanlanmış çalışmaları geciktirebilir ya da hiç tetiklemeyebilir. Kural:

  * elle başlatılan çalışma (workflow_dispatch) her zaman çalışır;
  * zamanlanmış çalışma, Berlin saatiyle 08:00 olmadıysa çalışmaz;
  * 08:00'den sonraysa, bugün (Berlin tarihi) raporu teslim etmiş başka bir zamanlanmış çalışma
    yoksa çalışır — böylece ilki atlanırsa ikincisi yedek görevi görür.

"Raporu teslim etmiş" = workflow'daki REPORT_STEP adımı başarıyla bitmiş. Kapıda duran
çalışmalarda bu adım `skipped` olur, başarısız olanlarda `failure` — ikisi de sayılmaz.

Yalnızca standart kütüphane ve `gh` CLI kullanır; sonucu GITHUB_OUTPUT'a `run=true|false` yazar.
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


def should_run(event_name: str, now_utc: datetime, reported: List[datetime]) -> tuple:
    """(çalışsın_mı, gerekçe)."""
    if event_name != "schedule":
        return True, f"{event_name} → her zaman çalışır"
    now = now_utc.astimezone(BERLIN)
    if now.hour < REPORT_HOUR:
        return False, f"Berlin {now:%H:%M} — henüz {REPORT_HOUR:02d}:00 olmadı"
    today = now.date()
    done = [r for r in reported if r.astimezone(BERLIN).date() == today]
    if done:
        return False, f"bugünkü rapor zaten {done[0].astimezone(BERLIN):%H:%M}'de gönderildi"
    return True, f"Berlin {now:%H:%M} — bugün henüz rapor yok"


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


def main(gh: Optional[Callable[[List[str]], str]] = None) -> int:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    now = datetime.now(timezone.utc)
    reported: List[datetime] = []
    if event == "schedule" and now.astimezone(BERLIN).hour >= REPORT_HOUR:
        try:
            reported = reported_runs(gh or _gh, os.environ.get("GITHUB_RUN_ID", ""))
        except (subprocess.CalledProcessError, OSError, ValueError, KeyError) as exc:
            # Geçmiş okunamazsa çalışmayı tercih et: fazladan bir yorum, kaçan rapordan iyidir.
            print(f"[!] Önceki çalışmalar okunamadı ({exc}); rapor yine de üretilecek.")
    run, reason = should_run(event, now, reported)
    print(f"run={str(run).lower()} — {reason}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"run={str(run).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
