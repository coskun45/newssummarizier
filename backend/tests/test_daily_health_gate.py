"""scripts/daily_health_gate.py — Daily Health workflow'unun bugün rapor üretip üretmeyeceğine karar verir."""
import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "daily-health.yml"
_spec = importlib.util.spec_from_file_location("daily_health_gate", _ROOT / "scripts" / "daily_health_gate.py")
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


# --- karar mantığı -------------------------------------------------------------------------------


def test_manual_run_always_runs():
    run, _ = gate.should_run("workflow_dispatch", _utc("2026-09-27T03:00:00"), [])
    assert run is True


def test_summer_first_cron_runs():
    # CEST: 06:17 UTC = 08:17 Berlin
    run, _ = gate.should_run("schedule", _utc("2026-09-27T06:17:00"), [])
    assert run is True


def test_summer_backup_cron_runs_when_first_was_dropped():
    # Bu sabahki hata: 06:00 UTC çalışması GitHub tarafından atlandı, 07:00 yedeği saat kapısında
    # durdu → gün boyu rapor yok. Yedek çalışma, bugün rapor yoksa çalışmalı.
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [])
    assert run is True


def test_backup_cron_skips_when_report_already_done_today():
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [_utc("2026-09-27T06:21:00")])
    assert run is False


def test_yesterdays_report_does_not_count():
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [_utc("2026-09-26T06:21:00")])
    assert run is True


def test_winter_first_cron_is_too_early():
    # CET: 06:17 UTC = 07:17 Berlin → henüz 08:00 olmadı
    run, _ = gate.should_run("schedule", _utc("2026-12-15T06:17:00"), [])
    assert run is False


def test_winter_first_cron_runs_if_delayed_past_eight():
    run, _ = gate.should_run("schedule", _utc("2026-12-15T07:02:00"), [])
    assert run is True


def test_winter_second_cron_runs():
    run, _ = gate.should_run("schedule", _utc("2026-12-15T07:17:00"), [])
    assert run is True


def test_berlin_day_boundary_uses_local_date():
    # 22:30 UTC 26 Eylül = 00:30 Berlin 27 Eylül; ertesi sabahki rapor bunu "bugün" saymamalı mı?
    # 00:30'daki çalışma Berlin'e göre 27 Eylül'dür → 27 Eylül için rapor yapılmış sayılır.
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [_utc("2026-09-26T22:30:00")])
    assert run is False


# --- GitHub'dan bugünkü raporları bulma ----------------------------------------------------------


def _fake_gh(runs, views):
    calls = []

    def gh(args):
        calls.append(args)
        if args[:2] == ["run", "list"]:
            return json.dumps(runs)
        if args[:2] == ["run", "view"]:
            return json.dumps(views[args[2]])
        raise AssertionError(args)

    gh.calls = calls
    return gh


def _view(report_conclusion):
    return {
        "jobs": [
            {
                "name": "Sunucu sağlık raporu",
                "steps": [
                    {"name": "Saat kapısı (08:00 Europe/Berlin)", "conclusion": "success"},
                    {"name": gate.REPORT_STEP, "conclusion": report_conclusion},
                ],
            }
        ]
    }


def test_reported_runs_only_counts_runs_that_delivered_the_report():
    runs = [
        {"databaseId": 3, "createdAt": "2026-09-27T07:17:05Z"},  # şu anki çalışma
        {"databaseId": 2, "createdAt": "2026-09-27T06:17:04Z"},  # kapıda durdu → adım skipped
        {"databaseId": 1, "createdAt": "2026-09-26T06:17:04Z"},  # dün, rapor verdi
        {"databaseId": 0, "createdAt": "2026-09-25T06:17:04Z"},  # başarısız
    ]
    views = {"2": _view("skipped"), "1": _view("success"), "0": _view("failure")}
    gh = _fake_gh(runs, views)

    reported = gate.reported_runs(gh, current_run_id="3")

    assert reported == [_utc("2026-09-26T06:17:04")]
    assert not any(c[:3] == ["run", "view", "3"] for c in gh.calls)


# --- workflow dosyası ----------------------------------------------------------------------------


def test_workflow_crons_avoid_top_of_hour():
    crons = re.findall(r'cron:\s*"([^"]+)"', _WORKFLOW.read_text(encoding="utf-8"))
    assert crons, "zamanlama bulunamadı"
    for cron in crons:
        assert cron.split()[0] != "0", f"saat başı zamanlaması GitHub'da atlanabiliyor: {cron}"


def test_workflow_uses_gate_script_and_report_step_name():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/daily_health_gate.py" in text
    assert f"name: {gate.REPORT_STEP}" in text
