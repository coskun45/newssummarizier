"""Block a push when feature code changed but features.json didn't.

Two entry points share one check:
- Claude Code PreToolUse hook (default): reads the tool call JSON on stdin and denies a
  `git push` command. The diff is taken against the branch's upstream (a new branch: master's upstream).
- git pre-push hook (`--pre-push <remote>`): reads git's `<local ref> <local sha> <remote ref>
  <remote sha>` lines on stdin and exits 1 to stop the push. Wired into `.git/hooks/pre-push`.

Feature-bearing paths mirror the `paths:` of `.claude/rules/features.md`. Pure bug fixes, refactors
and styling don't need a features.json entry — set FEATURES_OK=1 for that push to skip the check
(`FEATURES_OK=1 git push` in bash, `$env:FEATURES_OK=1; git push` in PowerShell).
"""
import json
import os
import re
import subprocess
import sys

FEATURES_JSON = "frontend/src/data/features.json"
FEATURE_PATHS = (
    "frontend/src/components/",
    "backend/app/api/routes/",
    "backend/app/agents/",
    "backend/app/tasks/",
    "backend/app/services/",
)
IGNORED_SUFFIXES = (".css",)
PUSH_RE = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?push\b")
BYPASS = "FEATURES_OK=1"
ZERO_SHA = re.compile(r"^0+$")


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def unlisted_feature_files(base, head="HEAD"):
    """Feature files changed in base...head when features.json wasn't; None if base is unknown."""
    diff = git("diff", "--name-only", f"{base}...{head}")
    if diff is None:
        return None
    changed = diff.splitlines()
    if FEATURES_JSON in changed:
        return []
    return [f for f in changed if f.startswith(FEATURE_PATHS) and not f.endswith(IGNORED_SUFFIXES)]


def explain(base, files, bypass_hint):
    listing = "\n".join(f"  - {f}" for f in files[:15])
    return (
        f"Push blocked: feature code changed since {base} but {FEATURES_JSON} was not updated.\n"
        f"Changed feature files:\n{listing}\n\n"
        "Review these commits against .claude/rules/features.md:\n"
        f"- A user-facing feature was added/changed/removed -> update {FEATURES_JSON} "
        "(Turkish title/description, latest version block), commit it, then push again.\n"
        f"- Only a bug fix / refactor / styling change -> no entry needed; {bypass_hint}"
    )


def claude_hook():
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not PUSH_RE.search(command) or BYPASS in command:
        return 0
    # A new branch has no upstream yet: compare with where master is pushed (not a stale origin).
    base = (git("rev-parse", "--abbrev-ref", "@{u}")
            or git("rev-parse", "--abbrev-ref", "master@{u}")
            or "origin/master")
    files = unlisted_feature_files(base)
    if not files:
        return 0  # nothing to flag, or unknown base — don't block on a check we can't run
    hint = f"re-run the same push as `{BYPASS} git push ...` (PowerShell: `$env:{BYPASS}; git push ...`)."
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": explain(base, files, hint),
        }
    }))
    return 0


def git_pre_push(remote):
    if os.environ.get("FEATURES_OK") == "1":
        return 0
    for line in sys.stdin.read().splitlines():
        parts = line.split()
        if len(parts) != 4:
            continue
        _, local_sha, _, remote_sha = parts
        if ZERO_SHA.match(local_sha):
            continue  # branch deletion
        # New remote branch: compare with the remote's master instead of an empty ref.
        base = f"{remote}/master" if ZERO_SHA.match(remote_sha) else remote_sha
        files = unlisted_feature_files(base, local_sha)
        if files:
            hint = f"push with `{BYPASS} git push ...` (or `$env:{BYPASS}; git push ...` in PowerShell)."
            print(explain(base, files, hint), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pre-push":
        sys.exit(git_pre_push(sys.argv[2] if len(sys.argv) > 2 else "origin"))
    sys.exit(claude_hook())
