---
paths:
  - "app/agents/**"
  - "app/services/summary_service.py"
  - "app/tasks/**"
---

# LangGraph News-Processing Agent

The pipeline is a `StateGraph` defined in `app/agents/graph.py`: `rss_fetcher` → `article_processor` → (conditional loop back to `article_processor` until done → `END`). State shape lives in `app/agents/state.py` (`NewsProcessingState`).

## Nodes
- **Nodes return a partial state dict, never mutate-and-return the whole state** — return only the keys that change (`current_article_index`, `processed_articles`, `should_continue`, ...). LangGraph merges them.
- **The conditional edge is driven by `should_continue` in state**, evaluated by `should_continue_processing`. Any node that finishes work MUST set `should_continue` correctly (`index + 1 < len(articles)`), or the loop hangs or stops early.
- **Each node opens its own `SessionLocal()` and closes it in `finally`** — agent code runs outside the request lifecycle, so it does NOT use `Depends(get_db)`. This is the one place direct `SessionLocal()` is correct (contrast [[api-routes]]).
- **Never let one article kill the run** — wrap per-article processing in try/except, log the failure via `crud.create_log(..., status="error", error_details=...)`, set the article `status="failed"`, and still advance `current_article_index`.
- **Every processing step writes a `ProcessingLog`** through `crud.create_log` with the acting `agent_name` (`web_scraper`, `topic_categorizer`, `summarizer`, ...). Keep this audit trail when adding steps.

## LLM / summaries
- **All OpenAI calls go through `app/services/summary_service.py`** (`categorize_and_prioritize_article`, `generate_summary`) — nodes never call the OpenAI SDK directly.
- **Summary functions MUST return `cost`, `tokens_used`, and `model_used`**, which are persisted on the `Summary` row and accumulated into `total_cost`. Preserve cost tracking — it feeds the cost-limit settings and stats endpoints.
- **Models and token limits come from `settings`** (`default_model`, `detailed_model`, `max_tokens_*` in `app/core/config.py`), not hardcoded strings.
- **Respect runtime settings stored in DB** — enabled summary types are read via `crud.get_setting(db, "enabled_summary_types")`, not config. Truncate content with `truncate_content` before summarizing.

## Scheduling
- **The periodic run is wired in `app/tasks/scheduler.py`** (started/stopped in the app lifespan) with the actual work in `app/tasks/background.py`. Initial feed fetch is intentionally manual — don't trigger fetches on startup.
