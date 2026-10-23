""".claude/hooks/ — Claude Code hooks that keep companion files and instruction files current."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parents[2] / ".claude" / "hooks"
REPO_ROOT = _HOOKS.parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


drift = _load("drift_check")
ctx = _load("session_context")


def _git(root, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=root,
                   check=True, capture_output=True)


def _write(root, rel, text="x"):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "master")
    _write(tmp_path, "backend/app/api/routes/articles.py", "v1")
    _write(tmp_path, "backend/app/core/config.py", "v1")
    _write(tmp_path, "frontend/src/data/features.json", "{}")
    _write(tmp_path, ".env.example", "A=1")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


# --- drift_check -------------------------------------------------------------------------------

def test_route_change_without_features_json_is_reported(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")

    reason = drift.check(repo, "s1")

    assert "features.json" in reason
    assert "backend/app/api/routes/articles.py" in reason


def test_same_changes_are_reported_only_once(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    assert drift.check(repo, "s1")

    assert drift.check(repo, "s1") is None


def test_further_change_after_report_is_reported_again(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    assert drift.check(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v3")

    assert drift.check(repo, "s1")


def test_companion_updated_in_session_is_fine(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    _write(repo, "frontend/src/data/features.json", '{"versions": []}')
    _write(repo, "backend/tests/test_articles.py", "def test_x(): pass")

    assert drift.check(repo, "s1") is None


def test_backend_change_without_test_asks_for_pytest(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    _write(repo, "frontend/src/data/features.json", '{"versions": []}')

    reason = drift.check(repo, "s1")

    assert "backend/tests/" in reason
    assert "features.json" not in reason.split("(changed")[0]


def test_frontend_change_without_spec_asks_for_playwright(repo):
    drift.baseline(repo, "s1")
    _write(repo, "frontend/src/hooks/useApi.ts", "v2")

    reason = drift.check(repo, "s1")

    assert "frontend/tests/" in reason
    assert "backend/tests/" not in reason


def test_any_new_test_file_satisfies_the_test_rules(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/db/crud.py", "v2")
    _write(repo, "backend/tests/test_new.py", "def test_x(): pass")
    _write(repo, "frontend/src/components/Foo/Foo.tsx", "v1")
    _write(repo, "frontend/tests/foo.spec.ts", "test")
    _write(repo, "frontend/src/data/features.json", '{"versions": []}')

    assert drift.check(repo, "s1") is None


def test_changes_from_before_the_session_are_ignored(repo):
    _write(repo, "backend/app/api/routes/articles.py", "v2")  # e.g. earlier on the branch
    drift.baseline(repo, "s1")

    assert drift.check(repo, "s1") is None


def test_committed_branch_changes_still_count(repo):
    _git(repo, "checkout", "-q", "-b", "feat/x")
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/new.py", "v1")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "route")

    assert "features.json" in drift.check(repo, "s1")


def test_config_change_asks_for_env_example(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/core/config.py", "v2")

    reason = drift.check(repo, "s1")

    assert ".env.example" in reason
    assert "features.json" not in reason


def test_no_snapshot_means_no_report(repo):
    _write(repo, "backend/app/api/routes/articles.py", "v2")

    assert drift.check(repo, "never-started") is None


def test_baseline_survives_resume(repo):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    drift.baseline(repo, "s1")  # SessionStart fires again on resume/compact

    assert drift.check(repo, "s1")


def test_stop_hook_active_never_reports(repo, monkeypatch, capsys):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    monkeypatch.setattr(drift, "ROOT", repo)
    monkeypatch.setattr("sys.argv", ["drift_check.py", "check"])
    monkeypatch.setattr("sys.stdin", _Stdin({"session_id": "s1", "stop_hook_active": True}))

    drift.main()

    assert capsys.readouterr().out == ""


def test_main_emits_stop_additional_context(repo, monkeypatch, capsys):
    drift.baseline(repo, "s1")
    _write(repo, "backend/app/api/routes/articles.py", "v2")
    monkeypatch.setattr(drift, "ROOT", repo)
    monkeypatch.setattr("sys.argv", ["drift_check.py", "check"])
    monkeypatch.setattr("sys.stdin", _Stdin({"session_id": "s1", "stop_hook_active": False}))

    drift.main()

    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "Stop"
    assert "features.json" in out["additionalContext"]


class _Stdin:
    def __init__(self, payload):
        self.text = json.dumps(payload)

    def read(self, *_):
        return self.text


# --- session_context ---------------------------------------------------------------------------

@pytest.mark.parametrize("glob,path,matches", [
    ("app/**", "app/db/models.py", True),
    ("app/api/routes/**", "app/api/routes/x.py", True),
    ("app/api/deps.py", "app/api/deps.py", True),
    ("src/*.ts", "src/a/b.ts", False),
    ("**/*.tsx", "src/components/A/A.tsx", True),
    ("tests/test_*prompt*.py", "tests/test_classification_prompt.py", True),
    ("backend/app/**", "app/db/models.py", False),
])
def test_glob_to_regex(glob, path, matches):
    assert bool(ctx.glob_to_regex(glob).match(path)) is matches


def test_rule_paths_reads_list_and_inline_forms():
    assert ctx.rule_paths('---\npaths:\n  - "app/**"\n  - "tests/**"\n---\n# X') == ["app/**", "tests/**"]
    assert ctx.rule_paths("---\npaths: src/**, tests/**\n---\n") == ["src/**", "tests/**"]
    assert ctx.rule_paths("# no frontmatter") == []


def test_dead_rule_globs_are_relative_to_the_claude_parent(repo):
    rule = '---\npaths:\n  - "{}"\n---\n# R\n'
    _write(repo, "backend/.claude/rules/ok.md", rule.format("app/api/routes/**"))
    _write(repo, "backend/.claude/rules/prefixed.md", rule.format("backend/app/**"))  # the #1 mistake
    _write(repo, ".claude/rules/root.md", rule.format("backend/app/core/config.py"))
    _write(repo, ".claude/rules/gone.md", rule.format("scripts/**"))

    assert ctx.dead_rule_globs(repo) == [
        (".claude/rules/gone.md", "scripts/**"),
        ("backend/.claude/rules/prefixed.md", "backend/app/**"),
    ]


def test_this_repos_rules_have_no_dead_globs():
    assert ctx.dead_rule_globs(REPO_ROOT) == []


def _memory(dir_, name, type_):
    _write(dir_, name, f"---\nname: {name}\ndescription: d\nmetadata:\n  type: {type_}\n---\nbody")


def test_new_feedback_memory_is_offered_for_promotion_weekly(tmp_path):
    mem, stamp = tmp_path / "memory", tmp_path / "state" / "memory_review.json"
    _memory(mem, "feedback_tests.md", "feedback")
    _memory(mem, "user_role.md", "user")
    _write(mem, "MEMORY.md", "- index")

    assert ctx.memory_to_promote(mem, stamp, now=10**10) == ["feedback_tests.md"]
    assert ctx.memory_to_promote(mem, stamp, now=10**10 + 3600) == []  # reviewed this week


def test_missing_memory_dir_offers_nothing(tmp_path):
    assert ctx.memory_to_promote(tmp_path / "nope", tmp_path / "stamp.json", now=10**10) == []


def test_build_context_mentions_dead_rule_and_memory(repo):
    _write(repo, ".claude/rules/gone.md", '---\npaths:\n  - "scripts/**"\n---\n')
    mem = repo.parent / "memory"
    _memory(mem, "project_x.md", "project")

    text = ctx.build_context(repo, mem, now=10**10)

    assert "scripts/**" in text
    assert "project_x.md" in text and "/add-rule" in text
