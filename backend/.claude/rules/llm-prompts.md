---
paths:
  - "app/services/summary_service.py"
  - "app/api/routes/prompts.py"
  - "app/api/routes/playground.py"
  - "app/db/seed.py"
  - "tests/test_*prompt*.py"
  - "tests/test_playground.py"
  - "tests/test_summary_service.py"
---

# LLM Prompts, Playground & Cost

`app/services/summary_service.py` owns every OpenAI call (see [[langgraph-agent]] for how nodes use
it). This rule covers the prompts it sends, the Playground dry-run, and cost tracking.

## Prompts are two parts: editable + locked
- **System prompt = editable text + a locked block rendered from code.** Editable: the active DB
  `SystemPrompt` row (Ayarlar › Sistem Promptları) or the built-in default. Locked:
  `build_classification_locked_text(topics)` (live topic list + JSON output contract) and
  `build_summarization_locked_text(...)` (per-type instructions + the Turkish language line). The
  locked block is always appended and shown read-only via `GET /api/prompts/{type}/locked`.
- **NEVER move anything the code parses into the editable text** — the topic list, the JSON shape,
  `importance`/`priority` values, the language line. An admin can erase editable text; the pipeline
  must still work. Change the locked template instead.
- **Locked templates use a single `re.sub`, not `str.format`** — the JSON examples contain literal
  braces, and one pass keeps a `{...}`-looking topic name from being re-substituted.
- **Blank / missing / inactive DB prompt → built-in default** (`_resolve_system_prompt`). Never let
  the pipeline send an empty system message.

## Changing a default prompt
- **Defaults live in the `_CATEGORIZATION_SYSTEM_PROMPT` / `_DEFAULT_SUMMARIZATION_SYSTEM_PROMPT`
  constants** and are seeded by `seed_system_prompts()` (`app/db/seed.py`) **only when the row is
  missing**. Editing a constant does NOT change existing installs.
- **To push a new default to existing DBs, write a one-time, marker-guarded migration** like
  `CLASSIFICATION_MIGRATION_KEY` in `seed.py` — guarded so a prompt the admin saves later is never
  overwritten on restart. Ask the developer first: it replaces text an admin may have tuned.
- **Prompt language is deliberate** — classification criteria are Turkish; the summarization prompt
  is English but demands Turkish output. Summaries must stay Turkish.

## Playground (`run_playground`, `/api/playground`)
- **The Playground is a dry run — it NEVER writes to the DB** (no summaries, no article updates, no
  logs). It must mirror the real pipeline's decisions (skip summarization on `unimportant`/failed
  classification unless `force_summarize`), so a pipeline behavior change updates both paths and
  `tests/test_playground.py`.
- **Per-stage failures are reported in the stage's `error`, not raised** — one failing summary type
  must not hide the others. `CostLimitExceededError` is the exception: raised before any call.
- **A response-shape change also updates the frontend** — `src/types/index.ts` and the stand-ins in
  `frontend/tests/helpers/mockApi.ts` (`makePlaygroundSettings`, `buildPlaygroundRunResult`,
  `LOCKED_CLASSIFICATION_TEXT`, `lockedSummarizationText`).

## Models, tokens & cost
- **Model names and token limits come from `settings`** (`default_model`, `detailed_model`,
  `max_tokens_*`), via `_summary_type_config`. Temperatures are the module constants.
- **A new model needs a `PRICING` entry** — unknown models silently fall back to `gpt-3.5-turbo`
  prices, so cost limits and stats go wrong without any error.
- **Call `check_cost_limits()` before model calls** and return `cost`/`tokens_used`/`model_used`
  from every call so they reach the `Summary` row and the stats.
- **A new summary type** = `DEFAULT_SUMMARY_INSTRUCTIONS` entry (`SUMMARY_TYPES` derives from it) +
  `_summary_type_config` + a `max_tokens_output_*` setting (config → `.env.example` → README) +
  frontend types and Ayarlar › Özet Türleri.

## Tests
- **No test calls OpenAI.** Stub with `monkeypatch` at the `summary_service` module level
  (`AsyncOpenAI`, `categorize_and_prioritize_article`, `generate_summary`, `SessionLocal`) — see
  `tests/test_summary_service.py`.
- Prompt assembly is covered by `test_classification_prompt.py` / `test_summarization_prompt.py`,
  the prompts API by `test_prompts.py`, the dry run by `test_playground.py`. Extend these when you
  change the matching code; assert on the locked block's presence, not on exact editable wording.
