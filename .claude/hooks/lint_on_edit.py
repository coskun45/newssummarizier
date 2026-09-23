"""PostToolUse hook: lint the file Claude just wrote, the same way CI does.

- backend/app/**/*.py      -> `ruff check` (from backend/, so backend/ruff.toml applies)
- frontend/src/**/*.ts(x)  -> eslint with --max-warnings 0 (from frontend/, .eslintrc.cjs)

On failure the lint output is fed back to Claude (decision: block) so it fixes it in the
same turn instead of CI catching it later. A missing linter is skipped silently.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(cmd, cwd):
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return result


def main():
    payload = json.load(sys.stdin)
    raw = payload.get("tool_input", {}).get("file_path") or payload.get("tool_response", {}).get("filePath")
    if not raw:
        return
    try:
        rel = Path(raw).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return  # outside the repo

    if rel.startswith("backend/app/") and rel.endswith(".py"):
        target = rel.removeprefix("backend/")
        result = run(["ruff", "check", target], ROOT / "backend")
        tool = "ruff"
    elif rel.startswith("frontend/src/") and rel.endswith((".ts", ".tsx")):
        eslint = ROOT / "frontend/node_modules/.bin" / ("eslint.cmd" if os.name == "nt" else "eslint")
        if not eslint.exists():
            return
        target = rel.removeprefix("frontend/")
        result = run([str(eslint), "--max-warnings", "0", target], ROOT / "frontend")
        tool = "eslint"
    else:
        return

    if result is None or result.returncode == 0:
        return
    output = (result.stdout + result.stderr).strip()[:4000]
    print(json.dumps({
        "decision": "block",
        "reason": f"{tool} failed on {rel} (CI runs the same check). Fix these before continuing:\n{output}",
    }))


if __name__ == "__main__":
    main()
