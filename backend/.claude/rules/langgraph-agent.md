---
paths:
  - "app/agents/**"
  - "app/services/summary_service.py"
  - "app/tasks/**"
---

# LangGraph News-Processing Agent

The pipeline is a `StateGraph` defined in `app/agents/graph.py`: `rss_fetcher` → `article_processor` → `END`. `article_processor` loops over **all** new articles itself in one graph step — never add a per-article graph loop again: it hit `GRAPH_RECURSION_LIMIT` on refreshes with ~100 new articles. State shape lives in `app/agents/state.py` (`NewsProcessingState`).

## Nodes
- **Nodes return a partial state dict, never mutate-and-return the whole state** — return only the keys that change. LangGraph merges them.
- **One processing path for new and re-processed articles.** The node only stores the RSS entry (`crud.create_article`) and hands its id to `summary_service.process_article(db, article_id)` — scrape → classify → topics → summaries → status. The "Error" re-process (`process_article_by_id`) calls the same function. Change processing there, never in a second copy (two copies drifted apart and caused #23).
- **Keep only a small outcome per article in state** (`url`, `status`, `created`, `cost`, `error`) — not its text. `created` is what the "X yeni makale" count sums; never derive it from a before/after diff of the global article count.
- **Each node opens its own `SessionLocal()` and closes it in `finally`** — agent code runs outside the request lifecycle, so it does NOT use `Depends(get_db)`. This is the one place direct `SessionLocal()` is correct (contrast [[api-routes]]).
- **Never let one article kill the run** — per-article processing is wrapped in try/except; a failure is logged via `crud.create_log(..., status="error", error_details=...)`, the article set to `status="failed"`, and the loop moves on.
- **Tests stub the steps on `summary_service`** (`extract_article_content`, `categorize_and_prioritize_article`, `generate_summary`), not on `app.agents.nodes` — see `tests/test_nodes.py::pipeline_env`.
- **Every processing step writes a `ProcessingLog`** through `crud.create_log` with the acting `agent_name` (`web_scraper`, `topic_categorizer`, `summarizer`, ...). Keep this audit trail when adding steps.

## LLM / summaries
- **All OpenAI calls go through `app/services/summary_service.py`** (`categorize_and_prioritize_article`, `generate_summary`) — nodes never call the OpenAI SDK directly.
- **Summary functions MUST return `cost`, `tokens_used`, and `model_used`**, which are persisted on the `Summary` row and accumulated into `total_cost`. Preserve cost tracking — it feeds the cost-limit settings and stats endpoints.
- **Models and token limits come from `settings`** (`default_model`, `detailed_model`, `max_tokens_*` in `app/core/config.py`), not hardcoded strings.
- **Respect runtime settings stored in DB** — enabled summary types only via `summary_service.get_enabled_summary_types(db)`, enabled topics only via `crud.get_enabled_topics(db)` (never re-parse the raw setting). Truncate content with `truncate_content` before summarizing.

## Scheduling
- **The periodic run is wired in `app/tasks/scheduler.py`** (started/stopped in the app lifespan) with the actual work in `app/tasks/background.py`. Its interval is the `feed_refresh_interval` DB setting (`crud.get_feed_refresh_interval`, default `FEED_REFRESH_INTERVAL`); `PUT /api/settings` applies a change via `reschedule_feed_processing`. Initial feed fetch is intentionally manual — don't trigger fetches on startup.
- **Startup resets interrupted work** — `crud.reset_interrupted_articles` moves `pending` AND `scraped` articles to `failed` so the Error tab can retry them. A new in-flight status must be added to `ERROR_EXCLUDED_STATUSES` and is then reset too.
