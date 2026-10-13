"""SessionStart hook: keep the Claude instruction files alive without anyone remembering to.

Adds `additionalContext` for Claude when:
- **a rule's `paths:` glob matches no file** — a renamed folder silently turns a rule off. Globs are
  matched relative to the directory that holds the rule's `.claude/` folder (see /add-rule).
- **auto memory has new `feedback`/`project` notes** — auto memory is machine-local, so a convention
  Claude learned there never reaches the team. At most once a week, Claude is asked to promote the
  project-wide ones into `.claude/rules/` with /add-rule.

State lives in `.claude/state/` (gitignored, per clone).
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MEMORY_REVIEW_INTERVAL = 7 * 24 * 3600
PROMOTABLE_TYPES = ("feedback", "project")


def glob_to_regex(pattern):
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def rule_paths(text):
    """The `paths:` globs from a rule's frontmatter (YAML list or comma-separated string)."""
    m = re.match(r"---\r?\n(.*?)\r?\n---", text, re.DOTALL)
    if not m:
        return []
    globs, in_paths = [], False
    for line in m.group(1).splitlines():
        if line.startswith("paths:"):
            inline = line[len("paths:"):].strip()
            if inline:
                return [g.strip().strip("\"'") for g in inline.split(",") if g.strip()]
            in_paths = True
        elif in_paths and line.lstrip().startswith("- "):
            globs.append(line.lstrip()[2:].strip().strip("\"'"))
        elif in_paths and line.strip():
            in_paths = False
    return globs


def repo_files(root):
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                         cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    return [p for p in out.stdout.split("\0") if p] if out.returncode == 0 else []


def dead_rule_globs(root):
    """[(rule file, glob)] for every glob that matches no file under the rule's base."""
    files = repo_files(root)
    dead = []
    for rule in sorted(p for p in files if re.search(r"(^|/)\.claude/rules/.+\.md$", p)):
        prefix = rule[:rule.index(".claude/rules/")]  # "" or "backend/" — the glob base
        under_base = [f[len(prefix):] for f in files if f.startswith(prefix)]
        for g in rule_paths((root / rule).read_text(encoding="utf-8")):
            rx = glob_to_regex(g)
            if not any(rx.match(f) for f in under_base):
                dead.append((rule, g))
    return dead


def memory_type(text):
    m = re.search(r"^\s*type:\s*(\w+)", text, re.MULTILINE)
    return m.group(1) if m else None


def memory_to_promote(memory_dir, stamp_file, now):
    """New promotable memory files, if a review is due; records the review time when it is."""
    try:
        last = json.loads(stamp_file.read_text(encoding="utf-8"))["last_review"]
    except (OSError, ValueError, KeyError):
        last = 0
    if now - last < MEMORY_REVIEW_INTERVAL or not memory_dir.is_dir():
        return []
    fresh = sorted(f.name for f in memory_dir.glob("*.md")
                   if f.name != "MEMORY.md" and f.stat().st_mtime > last
                   and memory_type(f.read_text(encoding="utf-8", errors="replace")) in PROMOTABLE_TYPES)
    if fresh:
        stamp_file.parent.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(json.dumps({"last_review": now}), encoding="utf-8")
    return fresh


def build_context(root, memory_dir, now):
    parts = []
    dead = dead_rule_globs(root)
    if dead:
        lines = "\n".join(f"- {rule}: `{g}`" for rule, g in dead)
        parts.append("These rule `paths:` globs match no file, so the rule never loads. Fix each glob "
                     "(relative to the folder holding its `.claude/`) or delete the rule when the code is "
                     f"gone, as a small side task alongside the user's request:\n{lines}")
    fresh = memory_to_promote(memory_dir, root / ".claude" / "state" / "memory_review.json", now)
    if fresh:
        parts.append("Auto memory has new notes that stay on this machine only: "
                     f"{', '.join(fresh)} (in {memory_dir}). After the user's current request, read them "
                     "and promote every project-wide convention or gotcha into `.claude/rules/` with "
                     "/add-rule (update an existing rule rather than duplicating it). Leave personal "
                     "preferences in memory. Mention what you promoted in your summary.")
    return "\n\n".join(parts)


def main():
    payload = json.load(sys.stdin)
    transcript = payload.get("transcript_path")
    memory_dir = Path(transcript).parent / "memory" if transcript else Path()
    context = build_context(ROOT, memory_dir, time.time())
    if context:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": context}}))


if __name__ == "__main__":
    main()
