---
paths:
  - "scripts/**"
  - "backend/tests/test_ensure_env.py"
  - "backend/tests/test_next_version.py"
  - "deploy.sh"
---

# Deploy / CI Scripts (`scripts/`)

Standalone Python scripts run outside the app: `ensure_env.py` prepares the server's single `.env`
(called by `deploy.sh` and `.github/workflows/deploy.yml`); `next_version.py` computes the release
version (called by `.github/workflows/ci-cd.yml`). See [[config-and-deploy]] and [[features]].

## Constraints
- **Standard library only, no `app.*` imports** — they run with the server's bare `python3` and in CI
  before any backend dependencies are installed.
- **Keep them idempotent and non-destructive.** `ensure_env.py` never overwrites a value already set in
  `.env`, only fills missing/placeholder keys, and takes its key set from `.env.example` — so a new
  setting reaches servers by adding it to `.env.example`, not by editing the script.
- **NEVER print secrets** — no `.env` values, passwords, API keys or generated JWT secrets on stdout,
  stderr or in exceptions (deploy logs are visible in GitHub Actions).
- **`next_version.py` reads tags from stdin and prints only `X.Y.Z` to stdout** — CI captures stdout
  as the version, so diagnostics go to stderr. The major comes from the highest `vN` in
  `features.json`; never hardcode a version.
- **Changing a script's CLI (args, flags, output) means updating every caller in the same change**:
  `deploy.sh`, `.github/workflows/deploy.yml`, `.github/workflows/ci-cd.yml`.
- Docstrings and user-facing messages are **Turkish**, matching the existing scripts.

## Tests
- **Each script has a pytest file in `backend/tests/test_<script>.py`** that loads it with
  `importlib.util.spec_from_file_location` (`scripts/` is not a package) — follow
  `test_ensure_env.py`. Use `tmp_path` for files and never touch the real `.env`.
- Cover idempotency (running twice changes nothing) and the "existing value is kept" cases.
