"""PreToolUse hook: block `git push` when feature code changed but features.json didn't.

Feature-bearing paths mirror the `paths:` of `.claude/rules/features.md`. The diff is taken
against the branch's upstream (falls back to origin/master). Pure bug fixes, refactors and
styling don't need a features.json entry — re-run the push with `# features-ok` appended
to acknowledge that and skip the check.
"""
import json
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
BYPASS_TOKEN = "features-ok"


def git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    payload = json.load(sys.stdin)
    command = payload.get("tool_input", {}).get("command", "")
    if not PUSH_RE.search(command) or BYPASS_TOKEN in command:
        return

    base = git("rev-parse", "--abbrev-ref", "@{u}") or "origin/master"
    diff = git("diff", "--name-only", f"{base}...HEAD")
    if diff is None:
        return  # unknown base ref — don't block on a check we can't run
    changed = diff.splitlines()

    feature_files = [
        f for f in changed
        if f.startswith(FEATURE_PATHS) and not f.endswith(IGNORED_SUFFIXES)
    ]
    if not feature_files or FEATURES_JSON in changed:
        return

    listing = "\n".join(f"  - {f}" for f in feature_files[:15])
    reason = (
        f"Push blocked: feature code changed since {base} but {FEATURES_JSON} was not updated.\n"
        f"Changed feature files:\n{listing}\n\n"
        "Review these commits against .claude/rules/features.md:\n"
        f"- A user-facing feature was added/changed/removed -> update {FEATURES_JSON} "
        "(Turkish title/description, latest version block), commit it, then push again.\n"
        "- Only a bug fix / refactor / styling change -> no entry needed; re-run the same push "
        f"with ` # {BYPASS_TOKEN}` appended."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
