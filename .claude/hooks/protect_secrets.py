"""PreToolUse hook: keep real secrets and personal settings out of Claude's edits and out of git.

- Write/Edit on `.env` / `.env.*` (except `.env.example`) is denied — the real `.env` holds
  OPENAI_API_KEY and DB credentials; only the human edits it. Change `.env.example` instead.
- A shell command that redirects into `.env` is denied for the same reason.
- `git add` naming `.env*` (not `.env.example`) or `.claude/settings.local.json` is denied —
  both are gitignored and must never be force-added.
"""
import json
import re
import sys
from pathlib import PurePath

SECRET_NAME = re.compile(r"^\.env(\..+)?$")
# `.env` / `.env.local` / `backend/.env` as a standalone token, but not `.env.example`
ENV_TOKEN = r"(?<![\w.-])(?:[\w./\\-]*[/\\])?\.env(?!\.example\b)(?:\.[\w-]+)?(?![\w.-])"
GIT_ADD = re.compile(r"\bgit\s+(?:-C\s+\S+\s+)?add\b[^;&|\n]*")
REDIRECT_TO_ENV = re.compile(r">>?\s*['\"]?" + ENV_TOKEN)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def is_secret_file(path):
    name = PurePath(path.replace("\\", "/")).name
    return bool(SECRET_NAME.match(name)) and name != ".env.example"


def main():
    payload = json.load(sys.stdin)
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})

    if tool in ("Write", "Edit"):
        path = tool_input.get("file_path", "")
        if is_secret_file(path):
            deny(f"{path} holds real secrets (OPENAI_API_KEY, DB credentials) and is edited by the "
                 "developer only. Change .env.example instead and tell the developer which value to set.")
        return

    command = tool_input.get("command", "")
    if REDIRECT_TO_ENV.search(command):
        deny("Writing into a real .env from the shell is blocked — it holds secrets. "
             "Change .env.example instead and tell the developer which value to set.")
        return
    for add in GIT_ADD.findall(command):
        if re.search(ENV_TOKEN, add) or "settings.local.json" in add:
            deny("git add of a .env file or .claude/settings.local.json is blocked — both are "
                 "gitignored on purpose (secrets / personal settings) and must never be committed.")
            return


if __name__ == "__main__":
    main()
