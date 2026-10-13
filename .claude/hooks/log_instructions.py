"""InstructionsLoaded hook: append which CLAUDE.md / rule file loaded, and why, to
`.claude/state/instructions.log` (JSON lines, gitignored). Answers "did my rule actually load when I
edited X?" — e.g. that a nested rule's `paths:` match relative to its own `.claude/` parent.
Observability only; it never changes what Claude sees.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / ".claude" / "state" / "instructions.log"
MAX_BYTES = 512 * 1024


def main():
    payload = json.load(sys.stdin)
    entry = {k: payload.get(k) for k in ("file_path", "load_reason", "globs", "trigger_file_path")}
    entry["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if LOG.exists() and LOG.stat().st_size > MAX_BYTES:  # keep it bounded: start over
        LOG.unlink()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
