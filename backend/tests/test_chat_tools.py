"""
Tests for the Asistan's tools (app/agents/analysis/): the SQL guard, the time resolver, the tool
executors and the Ayarlar on/off reader, plus the agent LLM call in summary_service.
"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.agents.analysis import tools
from app.agents.analysis.sql_guard import SqlRejected, validate_sql
from app.agents.analysis.time_range import mentions_period, named_by_user, resolve_time_range
from app.db import crud, models
from tests.conftest import _make_article, _make_feed

NOW = datetime(2026, 10, 28, 15, 0, tzinfo=ZoneInfo("Europe/Berlin"))  # a Wednesday


# ---------------------------------------------------------------------------
# SQL guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "DELETE FROM chat_articles",
    "WITH d AS (DELETE FROM articles RETURNING *) SELECT * FROM d",
    "SELECT 1; DROP TABLE articles",
    "SELECT * FROM users",
    "SELECT * FROM articles",
    "SELECT * FROM pg_catalog.pg_roles",
    "SELECT * FROM information_schema.tables",
    "SELECT set_config('role', 'postgres', true)",
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "UPDATE chat_articles SET title = 'x'",
    "",
    "SELEC nonsense",
    # a CTE named after a real table: inside its own body the name still means the table
    "WITH users AS (SELECT * FROM users) SELECT * FROM users",
    "WITH articles AS (SELECT * FROM articles) SELECT id FROM articles",
    # a later CTE is not visible in an earlier one, so "users" there is the real table
    "WITH a AS (SELECT * FROM users), users AS (SELECT 1 AS x) SELECT * FROM a",
    "SELECT * FROM (WITH users AS (SELECT * FROM users) SELECT * FROM users) s",
])
def test_sql_guard_rejects_anything_but_a_read_of_the_chat_views(query):
    with pytest.raises(SqlRejected):
        validate_sql(query, 200)


def test_sql_guard_adds_or_caps_the_row_limit():
    # One row over the cap, so the tool can tell a cut result from a complete one.
    assert validate_sql("SELECT id FROM chat_articles", 200).endswith("LIMIT 201")
    assert validate_sql("SELECT id FROM chat_articles LIMIT 5000", 200).endswith("LIMIT 201")
    assert validate_sql("SELECT id FROM chat_articles LIMIT 10", 200).endswith("LIMIT 10")
    assert validate_sql("SELECT id FROM chat_articles LIMIT 200", 200).endswith("LIMIT 200")


def test_sql_guard_allows_ctes_that_reference_earlier_ctes_or_views():
    validate_sql("WITH a AS (SELECT id FROM chat_articles), b AS (SELECT id FROM a) SELECT * FROM b", 200)
    validate_sql("WITH RECURSIVE n AS (SELECT 1 AS i UNION ALL SELECT i + 1 FROM n WHERE i < 3) SELECT * FROM n", 200)
    validate_sql("WITH a AS (SELECT id FROM chat_articles) SELECT * FROM (SELECT id FROM a) s", 200)


def test_sql_tool_says_when_the_result_was_cut_at_the_row_limit(agent_db, db_session, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "chat_sql_max_rows", 2)
    feed = _make_feed(db_session)
    for title in ("a", "b", "c"):
        _make_article(db_session, feed.id, title=title)

    cut = tools.run_sql_tool({"query": "SELECT id FROM chat_articles"}, "a1")
    whole = tools.run_sql_tool({"query": "SELECT id FROM chat_articles LIMIT 2"}, "a2")

    assert cut["artifact"]["truncated"] is True and len(cut["artifact"]["rows"]) == 2
    assert "sınırda kesildi" in cut["summary"]
    assert whole["artifact"]["truncated"] is False


def test_sql_guard_accepts_joins_ctes_and_aggregates_on_the_views():
    sql = validate_sql(
        "WITH t AS (SELECT article_id, topic_name FROM chat_article_topics) "
        "SELECT t.topic_name, count(*) FROM chat_articles a JOIN t ON t.article_id = a.id "
        "WHERE a.is_analyzable AND a.priority = 'high' GROUP BY 1 ORDER BY 2 DESC",
        200,
    )
    assert "chat_article_topics" in sql and "LIMIT 201" in sql


# ---------------------------------------------------------------------------
# Time resolver
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expression, start, end", [
    ("bugün", "2026-10-28T00:00:00", "2026-10-28T15:00:00"),
    ("dün", "2026-10-27T00:00:00", "2026-10-27T23:59:59"),
    ("geçen hafta", "2026-10-19T00:00:00", "2026-10-25T23:59:59"),
    ("bu hafta", "2026-10-26T00:00:00", "2026-10-28T15:00:00"),
    ("son 3 gün", "2026-10-26T00:00:00", "2026-10-28T15:00:00"),
    ("Son iki hafta", "2026-10-15T00:00:00", "2026-10-28T15:00:00"),
    ("geçen ay", "2026-09-01T00:00:00", "2026-09-30T23:59:59"),
    ("Ekim'de", "2026-10-01T00:00:00", "2026-10-28T15:00:00"),
    ("1-15 Ekim", "2026-10-01T00:00:00", "2026-10-15T23:59:59"),
    ("kasım", "2025-11-01T00:00:00", "2025-11-30T23:59:59"),  # a later month means last year's
    ("1 eylül - 15 ekim", "2026-09-01T00:00:00", "2026-10-15T23:59:59"),
    ("2026-10-01 - 2026-10-05", "2026-10-01T00:00:00", "2026-10-05T23:59:59"),
    # "since": from the start of the named period until now
    ("Ağustos sonundan bu yana", "2026-08-21T00:00:00", "2026-10-28T15:00:00"),
    ("1 eylülden beri", "2026-09-01T00:00:00", "2026-10-28T15:00:00"),
    ("ağustostan beri", "2026-08-01T00:00:00", "2026-10-28T15:00:00"),
    ("dünden beri", "2026-10-27T00:00:00", "2026-10-28T15:00:00"),
    ("1 Eylül'den beri", "2026-09-01T00:00:00", "2026-10-28T15:00:00"),
    ("Ekim'den bu yana", "2026-10-01T00:00:00", "2026-10-28T15:00:00"),
    ("Ağustos'tan itibaren", "2026-08-01T00:00:00", "2026-10-28T15:00:00"),
    # thirds of a month
    ("ekim başı", "2026-10-01T00:00:00", "2026-10-10T23:59:59"),
    ("eylül ortası", "2026-09-11T00:00:00", "2026-09-20T23:59:59"),
    ("şubat sonu", "2026-02-21T00:00:00", "2026-02-28T23:59:59"),
    # case suffixes the model copies from the question ("Son 30 günde ... ne oldu?")
    ("Son 30 günde", "2026-09-29T00:00:00", "2026-10-28T15:00:00"),
    ("son 7 günün", "2026-10-22T00:00:00", "2026-10-28T15:00:00"),
    ("son 24 saatte", "2026-10-27T15:00:00", "2026-10-28T15:00:00"),
    ("son 24 saatin", "2026-10-27T15:00:00", "2026-10-28T15:00:00"),
    ("bu haftanın", "2026-10-26T00:00:00", "2026-10-28T15:00:00"),
    ("geçen ayda", "2026-09-01T00:00:00", "2026-09-30T23:59:59"),
    ("bugünün", "2026-10-28T00:00:00", "2026-10-28T15:00:00"),
    # a month named with "ay" ("Ağustos ayında") and a month part with a case ending
    ("Ağustos ayında", "2026-08-01T00:00:00", "2026-08-31T23:59:59"),
    ("eylül ayı", "2026-09-01T00:00:00", "2026-09-30T23:59:59"),
    ("Eylül ayındaki", "2026-09-01T00:00:00", "2026-09-30T23:59:59"),
    ("Eylül ortasında", "2026-09-11T00:00:00", "2026-09-20T23:59:59"),
    ("ekim başında", "2026-10-01T00:00:00", "2026-10-10T23:59:59"),
    # the year first, or a year alone
    ("2026 Eylül", "2026-09-01T00:00:00", "2026-09-30T23:59:59"),
    ("2025 kasım ayı", "2025-11-01T00:00:00", "2025-11-30T23:59:59"),
    ("2019", "2019-01-01T00:00:00", "2019-12-31T23:59:59"),
    ("2019 yılında", "2019-01-01T00:00:00", "2019-12-31T23:59:59"),
    ("2019 yılının tamamı", "2019-01-01T00:00:00", "2019-12-31T23:59:59"),
    ("2026", "2026-01-01T00:00:00", "2026-10-28T15:00:00"),
    # two periods compared: the span covering both
    ("bu hafta ile geçen hafta", "2026-10-19T00:00:00", "2026-10-28T15:00:00"),
    ("Ağustos ve Eylül", "2026-08-01T00:00:00", "2026-09-30T23:59:59"),
    ("Ağustos ile Eylül arasında", "2026-08-01T00:00:00", "2026-09-30T23:59:59"),
    ("1 eylül ile 15 ekim arası", "2026-09-01T00:00:00", "2026-10-15T23:59:59"),
])
def test_time_resolver_turns_turkish_expressions_into_ranges(expression, start, end):
    resolved = resolve_time_range(expression, NOW)
    assert resolved["from"].startswith(start)
    assert resolved["to"].startswith(end)


@pytest.mark.parametrize("expression", ["", "ara sıra", "xyz'den beri", "31 şubat", "2026-10-05 - 2026-10-01",
                                        "0000"])  # a year datetime can't hold must not raise
def test_time_resolver_returns_none_when_it_does_not_understand(expression):
    assert resolve_time_range(expression, NOW) is None


@pytest.mark.parametrize("expression, expected", [
    ("son 5", False), ("son 5 haber", False), ("son", False),  # a count, not a period
    ("son 5 gün", True), ("2019", True), ("1-15 ekim", True), ("geçen hafta", True), ("dünden beri", True),
])
def test_mentions_period_needs_a_period_word_not_just_a_number(expression, expected):
    assert mentions_period(expression) is expected


@pytest.mark.parametrize("expression, user, expected", [
    # the model's own period, matched by accident on a word's first letters or a shared number
    ("Son 30 gün", "Güney Kore ekonomisi hakkında ne var?", False),
    ("Son 7 gün", "Gündemdeki konular neler?", False),
    ("Son 1 ay", "Ayrıntılı bir özet ver", False),
    ("dün", "Dünya haberleri", False),
    ("son 5 gün", "Guardian'dan son 5 haber", False),
    # the user's own period in other words or with case endings
    ("bu yıl", "Bu sene kaç haber var?", True),
    ("geçen yıl", "geçen sene neler oldu", True),
    ("Son 7 gün", "son bir haftada ne oldu", True),
    ("Son 30 gün", "Son 30 günde neler oldu?", True),
    ("1-15 Ekim", "Ekim'in ilk yarısı", True),
    ("eylül", "Eylül ayında kaç haber", True),
    ("2019", "2019 yılında", True),
    ("dün", "dünkü haberler", True),
])
def test_named_by_user_matches_whole_period_words(expression, user, expected):
    assert named_by_user(expression, [user]) is expected


def test_time_tool_also_returns_utc_bounds_for_sql():
    result = tools.run_time_tool({"expression": "dün"})
    assert result["ok"]
    data = json.loads(result["content"])
    # Timestamps are stored as naive UTC, so SQL compares against UTC text.
    assert data["from_utc"] == datetime.fromisoformat(data["from"]).astimezone(ZoneInfo("UTC")).strftime(
        "%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# SQL tool on the chat_* views
# ---------------------------------------------------------------------------

def _labelled_articles(db_session):
    feed = _make_feed(db_session, title="DW")
    _make_article(db_session, feed.id, title="ok high", priority="high", status="summarized")
    _make_article(db_session, feed.id, title="ok med", priority="med", status="summarized", importance="important")
    _make_article(db_session, feed.id, title="önemsiz", priority="low", importance="unimportant", status="filtered")
    _make_article(db_session, feed.id, title="hata", priority="high", status="failed")
    _make_article(db_session, feed.id, title="etiketsiz", status="failed")
    return feed


def test_is_analyzable_matches_the_analysis_tab_rule(agent_db, db_session):
    _labelled_articles(db_session)
    result = tools.run_sql_tool(
        {"query": "SELECT title FROM chat_articles WHERE is_analyzable ORDER BY title"}, "a1")
    assert result["ok"], result["summary"]
    assert [row[0] for row in result["artifact"]["rows"]] == ["ok high", "ok med"]
    assert crud.get_analysis_stats(db_session)["totals"]["total"] == 2


def test_sql_tool_reports_rejections_and_db_errors_to_the_model(agent_db, db_session):
    rejected = tools.run_sql_tool({"query": "SELECT * FROM users"}, "a1")
    assert not rejected["ok"] and "reddedildi" in json.loads(rejected["content"])["error"]
    broken = tools.run_sql_tool({"query": "SELECT no_such_column FROM chat_articles"}, "a2")
    assert not broken["ok"] and "hatası" in json.loads(broken["content"])["error"]


def _search_artifact(ids):
    return {"id": "a1", "kind": "table", "columns": ["id", "title", "score"],
            "rows": [[i, f"t{i}", 0.1] for i in ids], "truncated": False}


def test_sql_can_read_the_article_ids_of_an_earlier_table(agent_db, db_session):
    # Hybrid questions: count/group the articles a semantic search found, without copying ids.
    feed = _make_feed(db_session)
    ids = [_make_article(db_session, feed.id, priority=p, status="summarized").id for p in ("high", "med", "med")]
    artifacts = {"a1": _search_artifact(ids[:2])}

    result = tools.run_sql_tool({"query": "SELECT priority, COUNT(*) FROM chat_articles "
                                          "WHERE id IN (SELECT id FROM a1) GROUP BY priority ORDER BY priority"},
                                "a2", artifacts)
    assert result["ok"], result["summary"]
    assert result["artifact"]["rows"] == [["high", 1], ["med", 1]]

    # also when the query has its own CTEs (which may read a1 too)
    result = tools.run_sql_tool({"query": "WITH found AS (SELECT a.id FROM chat_articles a JOIN a1 ON a1.id = a.id) "
                                          "SELECT COUNT(*) FROM found"}, "a3", artifacts)
    assert result["ok"] and result["artifact"]["rows"] == [[2]]


def test_sql_table_reference_edges(agent_db, db_session):
    _make_feed(db_session)
    empty = tools.run_sql_tool({"query": "SELECT COUNT(*) FROM a1"}, "a2", {"a1": _search_artifact([])})
    assert empty["ok"] and empty["artifact"]["rows"] == [[0]]
    # a table that doesn't exist, or one without article ids (a chart, an aggregate), stays unreadable
    artifacts = {"a1": {"id": "a1", "kind": "table", "columns": ["priority", "n"], "rows": [["high", 1]]},
                 "a2": {"id": "a2", "kind": "chart", "title": "x"}}
    for name in ("a1", "a2", "a9"):
        result = tools.run_sql_tool({"query": f"SELECT * FROM {name}"}, "a3", artifacts)
        assert not result["ok"] and "okunamaz" in result["summary"]
    # an existing table without article ids says why, instead of "only the views can be read"
    result = tools.run_sql_tool({"query": "SELECT * FROM a1"}, "a3", artifacts)
    assert "haber id" in result["summary"]


def test_a_cut_table_is_not_readable_as_a_complete_id_set(agent_db, db_session):
    # A 200-row cut of 350 ids, counted in a later step, silently gave 200.
    _make_feed(db_session)
    cut = {**_search_artifact([1, 2, 3]), "truncated": True}
    assert tools.article_ids_of(cut) is None
    result = tools.run_sql_tool({"query": "SELECT COUNT(*) FROM a1"}, "a2", {"a1": cut})
    assert not result["ok"] and "kesilmiş" in result["summary"]


def test_sql_tables_keep_the_queries_own_ctes_and_comments(agent_db, db_session):
    _make_feed(db_session)
    artifacts = {"a1": _search_artifact([7, 8])}
    # the query defines its own a1: that one wins, no duplicate CTE name
    own = tools.run_sql_tool({"query": "WITH a1 AS (SELECT 1 AS id) SELECT id FROM a1"}, "a2", artifacts)
    assert own["ok"], own["summary"]
    assert own["artifact"]["rows"] == [[1]]
    # a leading comment before WITH
    commented = tools.run_sql_tool({"query": "-- önce bul" + chr(10) + "WITH x AS (SELECT id FROM a1) SELECT COUNT(*) FROM x"},
                                   "a3", artifacts)
    assert commented["ok"], commented["summary"]
    assert commented["artifact"]["rows"] == [[2]]


def test_the_shown_sql_is_the_models_query_not_the_injected_ids(agent_db, db_session):
    _make_feed(db_session)
    query = "SELECT COUNT(*) FROM a1"
    result = tools.run_sql_tool({"query": query}, "a2", {"a1": _search_artifact(list(range(1, 50)))})
    assert result["ok"]
    for shown in (result["sql"], result["artifact"]["sql"]):
        assert query in shown and "UNION ALL" not in shown


def test_sql_tool_keeps_the_full_result_as_artifact_and_shows_the_model_a_slice(agent_db, db_session):
    feed = _make_feed(db_session)
    for i in range(tools.LLM_TABLE_ROWS + 5):
        _make_article(db_session, feed.id, title=f"t{i}", priority="high", status="summarized")
    result = tools.run_sql_tool({"query": "SELECT id, title, fetched_at FROM chat_articles"}, "a1")
    content = json.loads(result["content"])
    assert len(result["artifact"]["rows"]) == tools.LLM_TABLE_ROWS + 5
    assert len(content["rows"]) == tools.LLM_TABLE_ROWS
    assert isinstance(content["rows"][0][2], str)  # datetimes serialised for JSON


# ---------------------------------------------------------------------------
# execute_tool / chart
# ---------------------------------------------------------------------------

def test_execute_tool_refuses_a_disabled_tool():
    result = asyncio.run(tools.execute_tool("render_chart", json.dumps({"type": "bar"}), ["sql"], "a1"))
    assert not result["ok"] and "kapalı" in json.loads(result["content"])["error"]


def test_execute_tool_reports_bad_arguments():
    result = asyncio.run(tools.execute_tool("resolve_time_range", "{not json", ["time"], "a1"))
    assert not result["ok"]


def test_chart_tool_validates_its_spec():
    good = tools.run_chart_tool({"type": "bar", "title": "T", "x": ["a", "b"],
                                 "series": [{"name": "s", "values": [1, 2]}]}, "a1")
    assert good["ok"] and good["chart"]["series"][0]["values"] == [1.0, 2.0]
    mismatched = tools.run_chart_tool({"type": "bar", "title": "T", "x": ["a", "b"],
                                       "series": [{"name": "s", "values": [1]}]}, "a1")
    assert not mismatched["ok"]
    assert not tools.run_chart_tool({"type": "pie", "title": "T", "x": ["a"],
                                     "series": [{"name": "s", "values": [1]}]}, "a1")["ok"]


# ---------------------------------------------------------------------------
# Enabled tools (Ayarlar)
# ---------------------------------------------------------------------------

def test_enabled_tools_default_to_every_available_tool(db_session):
    assert tools.get_enabled_chat_tools(db_session) == ["time", "sql", "chart"]


def test_enabled_tools_follow_the_setting_and_ignore_unavailable_ones(db_session):
    crud.set_setting(db_session, "chat_enabled_tools", "sql,web_search")
    assert tools.get_enabled_chat_tools(db_session) == ["sql"]


def test_a_setting_without_a_usable_data_tool_falls_back_to_all_available(db_session):
    crud.set_setting(db_session, "chat_enabled_tools", "chart")
    assert tools.get_enabled_chat_tools(db_session) == ["time", "sql", "chart"]


@pytest.mark.parametrize("value", ["sql,bogus", "chart,time", "semantic_search", ""])
def test_normalize_enabled_tools_rejects_unknown_or_no_data_tool(value):
    with pytest.raises(ValueError):
        tools.normalize_enabled_tools(value)


def test_normalize_enabled_tools_orders_canonically():
    assert tools.normalize_enabled_tools("chart, sql") == "sql,chart"


# ---------------------------------------------------------------------------
# summary_service.run_agent_llm — cost booking
# ---------------------------------------------------------------------------

def test_run_agent_llm_books_usage_and_returns_tool_calls(agent_db, db_session, monkeypatch):
    from app.services import summary_service

    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="run_sql", arguments='{"query": "SELECT 1"}'))
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[call]),
                                 finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=1000, completion_tokens=100),
    )
    sent = {}

    async def create(**kwargs):
        sent.update(kwargs)
        return response

    monkeypatch.setattr(summary_service, "get_openai_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    result = asyncio.run(summary_service.run_agent_llm(
        [{"role": "user", "content": "x"}], "gpt-4o-mini", 500, purpose="execute",
        tools=[{"type": "function", "function": {"name": "run_sql"}}],
    ))

    assert result["tool_calls"] == [{"id": "c1", "name": "run_sql", "arguments": '{"query": "SELECT 1"}'}]
    assert sent["tools"][0]["function"]["name"] == "run_sql"
    usage = db_session.query(models.LlmUsage).one()
    assert (usage.kind, usage.input_tokens, usage.output_tokens) == ("chat", 1000, 100)
    assert usage.cost == pytest.approx(result["cost"]) and result["cost"] > 0


def test_db_tools_do_not_block_the_event_loop(agent_db, db_session, monkeypatch):
    # A heavy model-written query runs up to CHAT_SQL_TIMEOUT_MS; meanwhile other requests and SSE
    # streams (keepalives, other users' runs) must keep being served.
    import time

    def slow_query(db, sql, timeout_ms, max_rows):
        time.sleep(0.3)
        return {"columns": ["n"], "rows": [[1]], "truncated": False}

    monkeypatch.setattr(crud, "run_readonly_query", slow_query)
    query = json.dumps({"query": "SELECT count(*) AS n FROM chat_articles"})

    async def scenario():
        done = asyncio.Event()
        ticks = 0

        async def ticker():
            nonlocal ticks
            while not done.is_set():
                await asyncio.sleep(0.01)
                ticks += 1

        async def call():
            try:
                return await tools.execute_tool("run_sql", query, ["sql"], "a1")
            finally:
                done.set()

        result, _ = await asyncio.gather(call(), ticker())
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result["ok"]
    assert ticks >= 10
