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


def test_report_after_eight_counts_for_today():
    # 06:21 UTC = 08:21 Berlin → bugünün raporu teslim edilmiş.
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [_utc("2026-09-27T06:21:00")])
    assert run is False


def test_night_outage_report_does_not_replace_daily_report():
    # 22:30 UTC 26 Eylül = 00:30 Berlin 27 Eylül: gece kesinti için analiz çalıştı (alert).
    # Bu, 08:00'den sonraki günlük raporun yerine geçmemeli.
    run, _ = gate.should_run("schedule", _utc("2026-09-27T07:17:00"), [_utc("2026-09-26T22:30:00")])
    assert run is True


# --- kesinti bildirimi ---------------------------------------------------------------------------


def test_app_down_without_open_outage_alerts():
    assert gate.outage_action("502", outage_open=False) == "alert"
    assert gate.outage_action("000", outage_open=False) == "alert"
    assert gate.outage_action("", outage_open=False) == "alert"


def test_app_down_with_open_outage_does_not_alert_again():
    # Aynı kesinti için 10 dakikada bir mail gitmemeli.
    assert gate.outage_action("502", outage_open=True) is None


def test_app_back_up_recovers_open_outage():
    assert gate.outage_action("200", outage_open=True) == "recover"


def test_app_up_without_outage_does_nothing():
    assert gate.outage_action("200", outage_open=False) is None


def _run_main(monkeypatch, tmp_path, *, status, outage_issues, daily=False):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("HEALTH_STATUS", status)
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    # Saatten bağımsız olsun: günlük rapor kararı sabitlenir.
    monkeypatch.setattr(gate, "should_run", lambda *a: (daily, "test"))
    monkeypatch.setattr(gate, "reported_runs", lambda *a: [])

    def gh(args):
        assert args[:2] == ["issue", "list"] and gate.OUTAGE_LABEL in args, args
        return json.dumps(outage_issues)

    assert gate.main(gh) == 0
    return dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").split())


def test_main_alert_runs_report_outside_daily_window(monkeypatch, tmp_path):
    # Uygulama gece çöktü: saat kapısı kapalı olsa da analiz + mail çalışmalı.
    out = _run_main(monkeypatch, tmp_path, status="502", outage_issues=[])
    assert out == {"run": "true", "alert": "true", "recover": "false"}


def test_main_open_outage_is_quiet(monkeypatch, tmp_path):
    out = _run_main(monkeypatch, tmp_path, status="000", outage_issues=[{"number": 7}])
    assert out == {"run": "false", "alert": "false", "recover": "false"}


def test_main_recover(monkeypatch, tmp_path):
    out = _run_main(monkeypatch, tmp_path, status="200", outage_issues=[{"number": 7}])
    assert out == {"run": "false", "alert": "false", "recover": "true"}


def test_main_daily_report_when_healthy(monkeypatch, tmp_path):
    out = _run_main(monkeypatch, tmp_path, status="200", outage_issues=[], daily=True)
    assert out == {"run": "true", "alert": "false", "recover": "false"}


def test_main_outage_lookup_failure_still_alerts(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    monkeypatch.setenv("HEALTH_STATUS", "000")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setattr(gate, "should_run", lambda *a: (False, "test"))

    def gh(args):
        raise OSError("gh yok")

    assert gate.main(gh) == 0
    assert "alert=true" in out.read_text(encoding="utf-8")


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


def test_workflow_uses_frequent_cron_not_fixed_times():
    # Sabit saatli 06:23/07:23 UTC cron'ları GitHub hiç tetiklemedi; günde bir raporu ancak sık bir
    # zamanlama + kapı garanti ediyor. Tek bir sabit saate geri dönülmemeli.
    crons = re.findall(r'cron:\s*"([^"]+)"', _WORKFLOW.read_text(encoding="utf-8"))
    assert any("/" in cron.split()[0] and cron.split()[1] == "*" for cron in crons), crons


def test_report_job_is_skipped_by_gate_job():
    # Kapıda duran çalışmalar Actions'ta gri "skipped" görünsün diye kapı ayrı bir job'dur.
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "needs: gate" in text
    assert "if: needs.gate.outputs.run == 'true'" in text
    assert "steps.gate.outputs.run" in text  # gate job'unun çıktısı
    assert "if: steps.gate.outputs.run" not in text  # adım bazlı eski koşullar kalmadı


def test_workflow_sends_mail_on_alert_and_recover():
    text = _WORKFLOW.read_text(encoding="utf-8")
    assert "HEALTH_STATUS: ${{ steps.http.outputs.status }}" in text  # kapı health kodunu görüyor
    assert "if: needs.gate.outputs.alert == 'true'" in text
    assert "if: needs.gate.outputs.recover == 'true'" in text
    assert "scripts/send_health_mail.py --kind down" in text
    assert "scripts/send_health_mail.py --kind recovered" in text
    assert f"--add-label {gate.OUTAGE_LABEL}" in text
    assert f"--remove-label {gate.OUTAGE_LABEL}" in text
