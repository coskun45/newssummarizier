"""scripts/next_version.py — deploy sürümünü features.json (major) + git tag'lerinden (minor) hesaplayan script."""
import importlib.util
import io
import json
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "next_version.py"
_spec = importlib.util.spec_from_file_location("next_version", _SCRIPT)
nv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv)


def _features(tmp_path, *versions):
    path = tmp_path / "features.json"
    path.write_text(
        json.dumps({"versions": [{"version": v, "title": "T", "features": []} for v in versions]}),
        encoding="utf-8",
    )
    return path


def _next(major, *tags):
    return nv.next_version(major, nv.parse_tags(tags))


def test_latest_major_is_highest_version_regardless_of_array_order(tmp_path):
    assert nv.latest_major(_features(tmp_path, "v1", "v10", "v2")) == 10


def test_latest_major_rejects_malformed_version(tmp_path):
    with pytest.raises(ValueError):
        nv.latest_major(_features(tmp_path, "v1", "2"))


def test_real_features_json_has_a_valid_major():
    assert nv.latest_major(_ROOT / "frontend" / "src" / "data" / "features.json") >= 1


def test_first_deploy_of_a_major_starts_at_minor_zero():
    assert _next(2) == "2.0.0"


def test_each_deploy_bumps_minor():
    assert _next(2, "v2.0.0") == "2.1.0"
    assert _next(2, "v2.3.0") == "2.4.0"


def test_minor_uses_numeric_not_string_ordering():
    assert _next(1, "v1.9.0", "v1.10.0") == "1.11.0"
    assert _next(1, "v1.10.0", "v1.9.0") == "1.11.0"


def test_new_features_major_resets_minor():
    assert _next(3, "v2.7.0", "v2.8.0") == "3.0.0"
    assert _next(3, "v2.8.0", "v3.0.0") == "3.1.0"


def test_invalid_tags_are_ignored():
    tags = nv.parse_tags(["latest", "v1.2", "1.2.3", "v1.2.3-rc1", "", "  v2.5.0  "])
    assert tags == [(2, 5, 0)]
    assert _next(2, "latest", "v2.x") == "2.0.0"


def test_tag_major_above_features_major_fails_instead_of_downgrading():
    with pytest.raises(ValueError, match="features.json"):
        _next(2, "v3.0.0")


def test_cli_reads_tags_from_stdin(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("v2.0.0\nv2.1.0\n"))
    assert nv.main(["--features", str(_features(tmp_path, "v1", "v2"))]) == 0
    assert capsys.readouterr().out.strip() == "2.2.0"


def test_cli_prints_valid_semver_for_empty_tag_list(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert nv.main(["--features", str(_features(tmp_path, "v1", "v2"))]) == 0
    assert re.fullmatch(r"2\.0\.0", capsys.readouterr().out.strip())


def test_cli_exits_nonzero_on_version_downgrade(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("v5.0.0\n"))
    assert nv.main(["--features", str(_features(tmp_path, "v1"))]) == 1
    assert "HATA" in capsys.readouterr().err
