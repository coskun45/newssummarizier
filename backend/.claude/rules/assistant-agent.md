---
paths:
  - "app/agents/analysis/**"
  - "app/services/chat_service.py"
  - "app/api/routes/chat.py"
  - "tests/test_chat.py"
  - "tests/test_chat_tools.py"
  - "tests/test_embeddings.py"
---

# Asistan (analysis chat agent + vector search)

A second LangGraph graph (`app/agents/analysis/graph.py`), separate from the ingestion pipeline:
understand → (clarify) → make_plan → (approve_plan) → execute_step ⇄ reflect → synthesize.
`chat_service.stream_turn` runs it and streams its events as SSE.

## Graph & state
- **There is no checkpointer and no `interrupt()`** — `langgraph==0.2.45` doesn't have it, and
  upgrading drags `langchain-core`/`langchain-openai` (the ingestion pipeline) along. "Wait for the
  user" = a node sets `pending` and the graph ends; `chat_service` stores the state JSON on
  `ChatConversation.agent_state`, and `graph.route_entry` resumes from `pending` + `resume`. Keep the
  state JSON-serialisable.
- **A node name must not equal a state key** — LangGraph refuses it at build time. That's why the
  planning node is `make_plan` (state has `plan`).
- **Every pass through `understand` starts a fresh plan** (`plan`/`current_step`/`replans`/`artifacts`
  reset): an answer to a clarifying question (also one asked mid-run by `reflect`) can change the
  scope, and carrying the old done steps made each turn re-show and re-run them (3/3 → 4/4 → 6/6).
- **Deterministic beats the model for scope the user picked**: a clarification answer that resolves
  as a period (`_answered_time_range`, "Tüm veriler" = no range) overrides the model's
  `time_expression` — the model kept the question's "son 24 saat" after the user chose "Son 30 gün".
  `understand` also checks `crud.get_article_coverage` for the range and asks right away (naming the
  newest article's date) when it holds no news, instead of letting the plan search an empty period;
  the coverage goes to plan/execute as `veri_kapsamı`. Filters listing every known topic/feed are
  dropped. `resolve_time_range` strips one case suffix ("son 30 günde", "bu haftanın").
- **Nodes emit UI events through `config["configurable"]["emit"]`** (`nodes._emit`). A new event type
  also needs `ChatEvent` in `frontend/src/types/index.ts` and handling in `ChatRun.tsx`'s `deriveRun`.

## LLM & cost
- **ALL agent OpenAI calls go through `summary_service.run_agent_llm` / `stream_agent_llm`** (book
  `llm_usage` kind `chat`, check cost limits first); embeddings through `summary_service.embed_texts`
  (kind `embedding`). Never call the SDK from `app/agents/analysis/`.
- Per-run budget (`CHAT_MAX_COST_PER_RUN`) is enforced in `execute_step`/`reflect`; a tool that costs
  (semantic search embeds the query) returns `cost` in its result so the node adds it.

## Tools
- **Catalog = `tools.CHAT_TOOLS`; availability ONLY via `unavailable_reason(name)`** (a later stage via
  `not_built_reason`, or infrastructure like `vector_support`); enabled state ONLY via
  `get_enabled_chat_tools(db)` (setting `chat_enabled_tools`). A tool reaches the model only if both hold.
- **A new tool needs**: a `CHAT_TOOLS` entry, a `_SCHEMAS` entry, a branch in `execute_tool`, and a
  label in `frontend/src/components/Chat/ChatRun.tsx` `TOOL_LABELS`. `execute_tool` never raises except
  `CostLimitExceededError` — errors go back to the model as `{"error": ...}` so it can retry.

## SQL tool security
- **Model-written SQL may only read `CHAT_VIEWS`** (`db/database.py`). `sql_guard.validate_sql`
  allow-lists relations AND `exp.Anonymous` functions — keep `set_config`, `pg_*`, `current_setting`
  etc. blocked: the app's DB session user is the superuser, so `set_config('role', …)` inside the
  query would undo the `SET LOCAL ROLE bulten_chat_ro` that `crud.run_readonly_query` applies.
- Views + the NOLOGIN read-only role are (re)created by `create_chat_views` in `init_db()`.
  **`chat_articles.is_analyzable` must mirror `crud.get_analysis_stats`'s rule** (high/med/low, not
  Önemsiz, not Error) — `test_is_analyzable_matches_the_analysis_tab_rule` guards it.
- Timestamps are naive UTC: the time tool returns `from_utc`/`to_utc` for SQL comparisons.
- **The guard's injected/capped LIMIT is `max_rows + 1`** so `run_readonly_query` can tell a cut result
  (`truncated`) from a complete one — a LIMIT of exactly max_rows made `truncated` always false.
- **A CTE name only shadows a relation where that CTE is in scope** (`_names_visible_cte`): inside its
  own body (non-RECURSIVE) and in earlier CTEs the name is the real table, so
  `WITH users AS (SELECT * FROM users)` must be rejected.
- **Blocking DB work in a tool runs via `asyncio.to_thread`** (SQL tool, semantic search's DB part):
  the graph runs on uvicorn's event loop, and a 5 s query froze every other request and SSE stream.
- `chat_service.stream_turn` runs the graph with `astream(stream_mode="values")` to know the last
  state's cost: a failed/stopped turn stores what it already spent, and a failed store still frees the
  conversation (`_free`), else it stays `running` (409 on every send/delete) until restart.
- **Frontend: `Dashboard` keeps `<Chat>` mounted once opened (hidden on other tabs)** — unmounting
  aborted the stream, which the backend treats as Durdur. Report tokens live in `useChatStream().tokens`,
  not in `events` (per-token array copies made streaming quadratic).

## Vector search
- **The article's text is embedded**, in chunks (`ArticleChunkEmbedding`, title in front of each chunk;
  only `summarized` articles): the scraped page, else the RSS text as plain text
  (`summary_service.article_search_text`). Paywalled / robots.txt-blocked sources (WSJ, NYT, Bloomberg,
  Independent Türkçe… — ~54% of summarized articles on the server) never get a page; embedding only
  `cleaned_content` left them out of search while the UI counted them as "missing" forever. Never get
  around robots.txt or paywalls to fill this gap. `crud._has_search_text` is the shared "has text"
  rule (backfill work list + `no_text` in the status); keep it in step with `article_search_text`. The pipeline step (`embed_article_safely` in `process_article`) never
  fails an article; the backfill (`tasks/background.embed_missing_articles_task`) catches up.
- `EmbeddingVector` is portable: pgvector `vector(dim)` on PostgreSQL, JSON text on SQLite and on a
  PostgreSQL without pgvector (tables must exist so article deletes cascading into them work);
  `init_db` drops/rebuilds those text-fallback tables once pgvector appears. A new vector table goes
  into `VECTOR_TABLES` and hangs off `article_id` (`crud._article_child_models` covers bulk deletes).
- **Filtered nearest-neighbour queries set `hnsw.iterative_scan = strict_order`** (`crud._nearest`):
  otherwise an HNSW scan yields only `ef_search` (40) candidates before the scope filter, and a
  selective filter returns few/no hits. Needs pgvector ≥ 0.8 — don't pin the image below it.
- **The DB image is `docker/postgres/Dockerfile` = `postgres:16-alpine` + pgvector built from source.**
  Don't switch to the Debian-based `pgvector/pgvector` image: the existing volume's musl collation
  would change under its text indexes.

## Tests
- **Use the `agent_db` fixture** — it points `SessionLocal` of `nodes`, `tools`, `chat_service`,
  `summary_service` and `tasks.background` at the test DB and creates the views. A module it misses
  silently queries the REAL PostgreSQL; add any new module that opens its own session there.
- **Script the LLM with `fake_agent_llm`** (`FakeAgentLLM.script(purpose, ...)`, `tool_call(...)`);
  unscripted stages get defaults. Pretend pgvector with `monkeypatch.setitem(database.vector_support, ...)`.
- The run limiter in `routes/chat.py` is process-wide; `test_chat.py` clears `chat._run_times` per test.
