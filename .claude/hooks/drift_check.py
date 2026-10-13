"""SessionStart + Stop hook: code changed, but the file that must change with it did not.

- `drift_check.py baseline` (SessionStart) snapshots the content hash of every file that differs from
  the integration branch (`master` merge-base) plus untracked files — so changes that existed before
  this session never trigger anything.
- `drift_check.py check` (Stop) compares against that snapshot. If this session touched a trigger
  path (e.g. a route) but not its companion (e.g. features.json), it keeps the turn going once with
  that feedback, so Claude updates the companion — or says why it isn't needed — in the same turn.
  The same set of changes is never reported twice, so the hook can't loop.

State lives in `.claude/state/` (gitignored, per clone).
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_MAX_AGE = 7 * 24 * 3600

# (trigger path prefixes, companion file, what to do). A companion counts as updated when it changed
# during this session.
RULES = [
    (("backend/app/api/routes/", "backend/app/agents/", "backend/app/tasks/", "frontend/src/components/"),
     "frontend/src/data/features.json",
     ("A user-facing feature may have changed but frontend/src/data/features.json did not "
      "(see .claude/rules/features.md). Add/edit/remove the entry — or, if this was a pure "
      "refactor/bug fix/styling change, say so in one line and stop.")),
    (("backend/app/core/config.py",),
     ".env.example",
     ("backend/app/core/config.py changed but .env.example did not. A new/renamed setting must land in "
      ".env.example and the README Docker env table too — or say why no setting changed.")),
    (("backend/app/db/models.py",),
     "backend/app/db/database.py",
     ("backend/app/db/models.py changed but backend/app/db/database.py did not. A new column must also "
      "be appended to `article_columns` in init_db() or existing PostgreSQL DBs never get it — or say "
      "why no column was added.")),
]


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    return result.stdout if result.returncode == 0 else None


def base_ref(root):
    for ref in ("master", "mygit/master", "origin/master"):
        base = git(root, "merge-base", "HEAD", ref)
        if base:
            return base.strip()
    return "HEAD"


def changed_files(root):
    """{path: content hash} for files differing from the merge-base, plus untracked ones."""
    tracked = git(root, "diff", "--name-only", "-z", base_ref(root)) or ""
    untracked = git(root, "ls-files", "--others", "--exclude-standard", "-z") or ""
    paths = {p for p in (tracked + untracked).split("\0") if p}
    hashes = {}
    for p in paths:
        f = root / p
        hashes[p] = hashlib.sha1(f.read_bytes()).hexdigest() if f.is_file() else "deleted"
    return hashes


def state_file(root, session_id):
    return root / ".claude" / "state" / f"drift-{session_id}.json"


def load_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state), encoding="utf-8")


def baseline(root, session_id):
    path = state_file(root, session_id)
    for old in path.parent.glob("drift-*.json"):  # drop snapshots of long-gone sessions
        if time.time() - old.stat().st_mtime > STATE_MAX_AGE:
            old.unlink(missing_ok=True)
    if load_state(path) is None:  # resume/compact keep the original snapshot
        save_state(path, {"baseline": changed_files(root), "warned": []})


def check(root, session_id):
    """Return the feedback for Claude, or None."""
    path = state_file(root, session_id)
    state = load_state(path)
    if state is None:
        return None  # no snapshot (hook added mid-session) — can't tell what is new
    before, now = state["baseline"], changed_files(root)
    touched = {p for p, h in now.items() if before.get(p) != h}
    touched |= {p for p in before if p not in now}  # reverted back to the base

    reasons, fingerprint = [], []
    for prefixes, companion, message in RULES:
        triggers = sorted(p for p in touched if p.startswith(prefixes))
        if triggers and companion not in touched:
            reasons.append(f"- {message} (changed: {', '.join(triggers)})")
            fingerprint.append([companion] + [f"{p}:{now.get(p)}" for p in triggers])
    if not reasons:
        return None
    key = hashlib.sha1(json.dumps(fingerprint).encode()).hexdigest()
    if key in state["warned"]:
        return None  # already reported this exact set of changes
    state["warned"].append(key)
    save_state(path, state)
    return "Companion files not updated this session:\n" + "\n".join(reasons)


def main():
    payload = json.load(sys.stdin)
    session_id = payload.get("session_id") or "unknown"
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "baseline":
        baseline(ROOT, session_id)
    elif mode == "check" and not payload.get("stop_hook_active"):
        reason = check(ROOT, session_id)
        if reason:  # guidance, not an error: additionalContext keeps the turn going without an error banner
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": reason}}))


if __name__ == "__main__":
    main()
