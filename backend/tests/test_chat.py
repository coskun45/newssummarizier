"""
Tests for app/api/routes/chat.py and the Asistan's analysis graph behind it (chat_service →
agents/analysis). The LLM is the FakeAgentLLM from conftest: each test scripts only the stages it
is about.
"""
import json
from datetime import datetime, timedelta

import pytest

from app.agents.analysis.time_range import resolve_time_range
from app.core.config import settings
from app.db import crud, models
from app.core.security import create_access_token, hash_password
from tests.conftest import FakeAgentLLM, _make_article, _make_feed


def _events(response):
    """The SSE `data:` events of a streamed response, in order."""
    return [json.loads(line[len("data: "):]) for line in response.text.splitlines() if line.startswith("data: ")]


def _types(events):
    return [e["type"] for e in events]


def _new_conversation(client, headers):
    response = client.post("/api/chat/conversations", json={}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def _send(client, headers, conversation_id, content="", action="message"):
    return client.post(f"/api/chat/conversations/{conversation_id}/messages",
                       json={"content": content, "action": action}, headers=headers)


@pytest.fixture(autouse=True)
def _reset_run_limit():
    """The per-user run limiter is process-wide; every test starts with a clean window."""
    from app.api.routes import chat
    chat._run_times.clear()
    yield
    chat._run_times.clear()


@pytest.fixture()
def chat_env(agent_db, fake_agent_llm, db_session):
    feed = _make_feed(db_session, title="DW")
    _make_article(db_session, feed.id, title="A", priority="high", status="summarized")
    _make_article(db_session, feed.id, title="B", priority="low", status="summarized")
    return fake_agent_llm


# ---------------------------------------------------------------------------
# Conversations CRUD + ownership
# ---------------------------------------------------------------------------

def test_chat_requires_auth(client):
    assert client.get("/api/chat/conversations").status_code == 401
    assert client.get("/api/chat/tools").status_code == 401


def test_conversation_crud(client, auth_headers):
    conversation_id = _new_conversation(client, auth_headers)
    listed = client.get("/api/chat/conversations", headers=auth_headers).json()
    assert [c["id"] for c in listed] == [conversation_id]
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["title"] == "Yeni sohbet" and detail["messages"] == [] and detail["status"] == "idle"
    assert client.delete(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).status_code == 404


def test_another_users_conversation_is_not_found(client, auth_headers, db_session, chat_env):
    other = crud.create_user(db_session, email="other@example.com", hashed_password=hash_password("x12345678"))
    other_headers = {"Authorization": f"Bearer {create_access_token({'sub': str(other.id)})}"}
    conversation_id = _new_conversation(client, other_headers)

    assert client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).status_code == 404
    assert client.delete(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).status_code == 404
    assert _send(client, auth_headers, conversation_id, "soru").status_code == 404
    assert client.get("/api/chat/conversations", headers=auth_headers).json() == []


def test_deleting_a_user_deletes_their_conversations(client, auth_headers, test_user, db_session):
    _new_conversation(client, auth_headers)
    crud.delete_user(db_session, test_user.id)
    assert db_session.query(models.ChatConversation).count() == 0


def test_empty_message_is_rejected(client, auth_headers, chat_env):
    conversation_id = _new_conversation(client, auth_headers)
    assert _send(client, auth_headers, conversation_id, "   ").status_code == 400


def test_a_second_run_on_a_running_conversation_is_rejected(client, auth_headers, db_session, chat_env):
    conversation_id = _new_conversation(client, auth_headers)
    crud.update_chat_conversation(db_session, conversation_id, status="running")
    assert _send(client, auth_headers, conversation_id, "soru").status_code == 409


def test_too_many_runs_are_throttled(client, auth_headers, chat_env, monkeypatch):
    from app.api.routes import chat
    monkeypatch.setattr(chat, "MAX_RUNS_PER_WINDOW", 1)
    conversation_id = _new_conversation(client, auth_headers)
    assert _send(client, auth_headers, conversation_id, "bir").status_code == 200
    assert _send(client, auth_headers, conversation_id, "iki").status_code == 429


def test_approve_plan_without_a_waiting_plan_is_rejected(client, auth_headers, chat_env):
    conversation_id = _new_conversation(client, auth_headers)
    assert _send(client, auth_headers, conversation_id, action="approve_plan").status_code == 409


# ---------------------------------------------------------------------------
# A full run: understand → plan → execute (tools) → reflect → report
# ---------------------------------------------------------------------------

def test_a_clear_question_runs_through_to_a_streamed_report(client, auth_headers, db_session, chat_env):
    chat_env.script("plan", {"steps": [{"goal": "Önem dağılımı", "tool": "sql"},
                                       {"goal": "Grafik", "tool": "chart"}]})
    chat_env.script("execute",
                    FakeAgentLLM.tool_call("run_sql", query="SELECT priority, count(*) AS n FROM chat_articles "
                                                            "WHERE is_analyzable GROUP BY priority ORDER BY priority"),
                    "1 high, 1 low.",
                    FakeAgentLLM.tool_call("render_chart", type="bar", title="Dağılım", x=["high", "low"],
                                           series=[{"name": "Haber", "values": [1, 1]}]),
                    "Grafik çizildi.")
    conversation_id = _new_conversation(client, auth_headers)

    response = _send(client, auth_headers, conversation_id, "Önem seviyelerinin dağılımı nedir?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response)
    types = _types(events)
    assert types[:4] == ["phase", "intent", "phase", "plan"]
    assert "clarification" not in types
    sql_result = next(e for e in events if e["type"] == "tool_result" and e["tool"] == "sql")
    assert sql_result["ok"] and sql_result["summary"] == "2 satır"
    assert next(e for e in events if e["type"] == "chart")["chart"]["title"] == "Dağılım"
    assert [e["status"] for e in events if e["type"] == "step_result"] == ["done", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == chat_env.report
    assert types[-1] == "done" and events[-1]["status"] == "idle"

    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["status"] == "idle"
    assert detail["title"] == "Önem seviyelerinin dağılımı nedir?"
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assistant = detail["messages"][1]
    assert assistant["content"] == chat_env.report
    assert "token" not in _types(assistant["events"]) and "chart" in _types(assistant["events"])
    assert detail["messages"][1]["id"] == events[-1]["message_id"]


def test_the_next_question_gets_the_previous_turn_as_context(client, auth_headers, chat_env):
    conversation_id = _new_conversation(client, auth_headers)
    _send(client, auth_headers, conversation_id, "İlk soru")
    _send(client, auth_headers, conversation_id, "Peki ya geçen hafta?")
    understand_calls = [c for c in chat_env.calls if c["purpose"] == "understand"]
    context = json.loads(understand_calls[-1]["messages"][1]["content"])
    assert context["soru"] == "Peki ya geçen hafta?"
    assert [h["role"] for h in context["konuşma_geçmişi"]] == ["user", "assistant"]
    assert context["konuşma_geçmişi"][0]["content"] == "İlk soru"


def test_a_disabled_tool_is_never_offered_to_the_model(client, auth_headers, db_session, chat_env):
    crud.set_setting(db_session, "chat_enabled_tools", "sql")
    chat_env.script("plan", {"steps": [{"goal": "Say", "tool": "sql"}, {"goal": "Çiz", "tool": "chart"}]})
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Dağılım?"))

    offered = {t["function"]["name"] for c in chat_env.calls if c["purpose"] == "execute" for t in c["tools"] or []}
    assert offered == {"run_sql"}
    plan = next(e for e in events if e["type"] == "plan")
    assert [s["tool"] for s in plan["steps"]] == ["sql"]  # the chart step was dropped
    report_input = json.loads([c for c in chat_env.calls if c["purpose"] == "report"][0]["messages"][1]["content"])
    assert any("Grafik" in note for note in report_input["sınırlamalar"])


# ---------------------------------------------------------------------------
# Clarification: the run stops, the answer resumes it
# ---------------------------------------------------------------------------

def test_an_ambiguous_question_asks_first_and_the_answer_resumes(client, auth_headers, chat_env):
    question = {"question": "Hangi dönem?", "options": ["Son 7 gün", "Son 30 gün"]}
    chat_env.script("understand",
                    {"restatement": "Durum özeti", "open_questions": [question]},
                    {"restatement": "Son 7 günün özeti", "time_expression": "son 7 gün", "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)

    first = _events(_send(client, auth_headers, conversation_id, "Durum nasıl?"))

    assert "plan" not in _types(first)
    clarification = next(e for e in first if e["type"] == "clarification")
    assert clarification["questions"] == [question]
    assert first[-1]["status"] == "awaiting_clarification"
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["status"] == "awaiting_clarification"
    assert detail["pending"]["questions"] == [question]

    second = _events(_send(client, auth_headers, conversation_id, "Son 7 gün"))

    assert "plan" in _types(second) and second[-1]["status"] == "idle"
    resumed = json.loads([c for c in chat_env.calls if c["purpose"] == "understand"][1]["messages"][1]["content"])
    assert resumed["soru"] == "Durum nasıl?"
    assert resumed["netleştirmeler"] == [{"questions": [question], "answer": "Son 7 gün"}]
    intent = next(e for e in second if e["type"] == "intent")
    assert intent["time_range"]["label"] == "Son 7 gün"


def test_clarification_rounds_are_capped(client, auth_headers, chat_env, monkeypatch):
    monkeypatch.setattr(settings, "chat_max_clarify_rounds", 1)
    always_ask = {"restatement": "?", "open_questions": [{"question": "Hangi konu?", "options": ["A", "B"]}]}
    chat_env.script("understand", always_ask, always_ask)
    conversation_id = _new_conversation(client, auth_headers)

    _send(client, auth_headers, conversation_id, "Belirsiz soru")
    second = _events(_send(client, auth_headers, conversation_id, "A"))

    assert "clarification" not in _types(second)
    assert second[-1]["status"] == "idle"
    intent = next(e for e in second if e["type"] == "intent")
    assert any("varsayıldı" in a for a in intent["assumptions"])


def test_an_unknown_time_expression_becomes_a_clarifying_question(client, auth_headers, chat_env):
    chat_env.script("understand", {"restatement": "x", "time_expression": "seçimlerden beri", "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Seçimlerden beri ne oldu?"))
    clarification = next(e for e in events if e["type"] == "clarification")
    assert "seçimlerden beri" in clarification["questions"][0]["question"]


def test_a_word_without_a_period_is_not_asked_about(client, auth_headers, chat_env):
    # "Guardian'dan gelen son 5 haber": the model took "son" for a period and the user was asked
    # which one; it only counts articles, so the question runs over all data.
    chat_env.script("understand", {"restatement": "x", "time_expression": "son", "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Guardian'dan gelen son 5 haber hangileri?"))
    assert "clarification" not in _types(events)
    assert next(e for e in events if e["type"] == "intent")["time_range"] is None


def test_a_period_the_user_never_named_is_ignored(client, auth_headers, chat_env):
    # "Gazze'de yaşanan saldırılar hakkında hangi haberler var?" came back with time_expression
    # "Son 30 gün" and the search missed the September articles.
    chat_env.script("understand", {"restatement": "x", "time_expression": "Son 30 gün", "entities": ["Gazze"],
                                   "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id,
                           "Gazze'de yaşanan saldırılar hakkında hangi haberler var?"))
    assert next(e for e in events if e["type"] == "intent")["time_range"] is None


@pytest.mark.parametrize("question, expression", [
    ("Son 30 günde neler oldu?", "son 30 gün"),
    ("Geçen haftaki haberler", "geçen hafta"),
    ("Ekim'in ilk yarısı", "1-15 Ekim"),
])
def test_a_period_from_the_users_words_is_kept(client, auth_headers, db_session, chat_env, question, expression):
    chat_env.script("understand", {"restatement": "x", "time_expression": expression, "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, question))
    assert next(e for e in events if e["type"] == "intent")["time_range"] is not None


def test_a_year_question_about_a_resolved_period_is_not_asked(client, auth_headers, db_session, chat_env):
    # "Eylül ayında kaç haber?": the model asked "Hangi yılın Eylül'ü?" although a month without a
    # year is the most recent one and the resolver already picked it.
    september = datetime.fromisoformat(resolve_time_range("eylül")["from"]).replace(tzinfo=None) + timedelta(days=2)
    _make_article(db_session, crud.get_feeds(db_session)[0].id, title="Eylül", priority="med",
                  status="summarized", published_at=september)
    chat_env.script("understand", {"restatement": "x", "time_expression": "Eylül ayında", "open_questions": [
        {"question": "Hangi yılın Eylül ayını kastediyorsunuz?", "options": ["2026", "Başka bir yıl"]}]})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Eylül ayında kaç önemli haber var?"))
    assert "clarification" not in _types(events)
    assert next(e for e in events if e["type"] == "intent")["time_range"]["label"] == "eylül"


def test_the_report_cannot_mistake_a_table_id_for_an_article_id(client, auth_headers, chat_env):
    # The report model saw {"id": "a1", ...} for a result table and cited it as article [#1].
    chat_env.script("plan", {"steps": [{"goal": "Say", "tool": "sql"}]})
    chat_env.script("execute", FakeAgentLLM.tool_call("run_sql", query="SELECT count(*) AS n FROM chat_articles"),
                    "Bulgu.")
    conversation_id = _new_conversation(client, auth_headers)
    _send(client, auth_headers, conversation_id, "Kaç haber var?")
    report_input = json.loads(next(c for c in chat_env.calls if c["purpose"] == "report")["messages"][1]["content"])
    tables = report_input["tablolar_ve_grafikler"]
    assert tables and all("id" not in table for table in tables)
    assert tables[0]["tablo"] == "a1"


def test_the_data_model_ties_importance_level_to_priority():
    # "önem seviyelerine göre" was grouped by importance (important/unimportant): one useless bucket.
    from app.agents.analysis import prompts
    assert "önem seviyesi" in prompts.DATA_MODEL.split("priority", 1)[1].split("\n", 1)[0]
    assert "importance'a göre gruplama" in prompts.DATA_MODEL


def test_a_general_question_without_a_period_uses_the_last_7_days(client, auth_headers, chat_env):
    # "Haberler nasıl?": no period named, but the answer depends on one → last 7 days, said openly,
    # instead of asking (or silently summarising all data).
    chat_env.script("understand", {"restatement": "Gündem", "time_expression": None, "needs_period": True,
                                   "open_questions": [{"question": "Hangi dönem?", "options": ["Son 7 gün", "Bu ay"]}]})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Haberler nasıl?"))
    assert "clarification" not in _types(events)
    intent = next(e for e in events if e["type"] == "intent")
    assert intent["time_range"]["label"] == "Son 7 gün"
    assert any("son 7 gün" in a.lower() for a in intent["assumptions"])
    report_input = json.loads(next(c for c in chat_env.calls if c["purpose"] == "report")["messages"][1]["content"])
    assert any("son 7 gün" in a.lower() for a in report_input["varsayımlar"])


@pytest.mark.parametrize("intent", [
    {"needs_period": False},
    # a question about a named event/topic searches all data even if the model flags a period
    {"needs_period": True, "entities": ["Gazze"]},
    {"needs_period": True, "topics": ["DW"]},
])
def test_a_question_over_all_data_gets_no_default_period(client, auth_headers, chat_env, intent):
    chat_env.script("understand", {"restatement": "x", "time_expression": None, "open_questions": [], **intent})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Gazze'deki saldırılar hakkında ne var?"))
    assert next(e for e in events if e["type"] == "intent")["time_range"] is None
    # the planner must not see the flag either: it called the time tool with "son 7 gün" itself
    assert not _plan_inputs(chat_env)[0]["niyet"].get("needs_period")


def test_a_later_step_can_query_an_earlier_steps_articles(client, auth_headers, chat_env):
    chat_env.script("plan", {"steps": [{"goal": "Bul", "tool": "sql"}, {"goal": "Say", "tool": "sql"}]})
    chat_env.script("execute",
                    FakeAgentLLM.tool_call("run_sql", query="SELECT id FROM chat_articles WHERE priority = 'high'"),
                    "Bulundu.",
                    FakeAgentLLM.tool_call("run_sql", query="SELECT COUNT(*) AS n FROM chat_articles "
                                                            "WHERE id IN (SELECT id FROM a1)"),
                    "Sayıldı.")
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Yüksek önemli haberleri say"))
    results = [e for e in events if e["type"] == "tool_result"]
    assert [r["ok"] for r in results] == [True, True]
    assert results[1]["summary"] == "1 satır"


def _understand_inputs(fake):
    return [json.loads(c["messages"][1]["content"]) for c in fake.calls if c["purpose"] == "understand"]


def _plan_inputs(fake):
    return [json.loads(c["messages"][1]["content"]) for c in fake.calls if c["purpose"] == "plan"]


def test_the_answer_to_a_mid_run_question_starts_a_fresh_plan(client, auth_headers, chat_env):
    # The reflect stage asks after a step; the answer changes the scope, so the old steps must not
    # be carried (and shown) again in the next turn's plan.
    chat_env.script("plan", {"steps": [{"goal": "Eski adım", "tool": "sql"}]},
                    {"steps": [{"goal": "Yeni adım", "tool": "sql"}]})
    chat_env.script("reflect", {"decision": "ask_user", "questions": [
        {"question": "Aralığı genişletelim mi?", "options": ["Son 7 gün", "Son 30 gün"]}]})
    conversation_id = _new_conversation(client, auth_headers)

    first = _events(_send(client, auth_headers, conversation_id, "Soru"))
    assert first[-1]["status"] == "awaiting_clarification"

    second = _events(_send(client, auth_headers, conversation_id, "Son 30 gün"))

    plan = next(e for e in second if e["type"] == "plan")
    assert [s["goal"] for s in plan["steps"]] == ["Yeni adım"]
    assert [s["id"] for s in plan["steps"]] == [1]
    assert [e["goal"] for e in second if e["type"] == "step_started"] == ["Yeni adım"]
    assert _plan_inputs(chat_env)[1]["önceki_adımlar"] == []


def test_a_time_choice_in_the_clarification_answer_overrides_the_question(client, auth_headers, chat_env):
    # The model keeps the question's "son 24 saat" even after the user picked "Son 30 gün".
    ask = {"restatement": "En önemli haberler", "time_expression": "son 24 saat",
           "open_questions": [{"question": "Hangi dönem?", "options": ["Son 7 gün", "Son 30 gün"]}]}
    keep = {"restatement": "En önemli haberler", "time_expression": "son 24 saat", "open_questions": []}
    chat_env.script("understand", ask, keep)
    conversation_id = _new_conversation(client, auth_headers)

    _send(client, auth_headers, conversation_id, "Son 24 saatin en önemli 5 haberi hangileri?")
    second = _events(_send(client, auth_headers, conversation_id, "Son 30 gün"))

    intent = next(e for e in second if e["type"] == "intent")
    assert intent["time_range"]["label"] == "Son 30 gün"
    assert _plan_inputs(chat_env)[0]["zaman_aralığı"]["label"] == "Son 30 gün"


def test_all_data_as_the_clarification_answer_clears_the_time_range(client, auth_headers, chat_env):
    ask = {"restatement": "x", "time_expression": "son 24 saat",
           "open_questions": [{"question": "Hangi dönem?", "options": ["Son 7 gün", "Tüm veriler"]}]}
    keep = {"restatement": "x", "time_expression": "son 24 saat", "open_questions": []}
    chat_env.script("understand", ask, keep)
    conversation_id = _new_conversation(client, auth_headers)

    _send(client, auth_headers, conversation_id, "Son 24 saat?")
    second = _events(_send(client, auth_headers, conversation_id, "Tüm veriler"))

    assert next(e for e in second if e["type"] == "intent")["time_range"] is None
    assert "clarification" not in _types(second)


def test_an_empty_time_range_is_asked_about_before_planning(client, auth_headers, db_session, agent_db,
                                                            fake_agent_llm):
    from datetime import datetime, timedelta
    from app.agents.analysis import nodes
    feed = _make_feed(db_session, title="DW")
    five_days_ago = datetime.utcnow() - timedelta(days=5)
    _make_article(db_session, feed.id, title="Eski", priority="high", status="summarized",
                  published_at=five_days_ago)
    fake_agent_llm.script("understand",
                          {"restatement": "Son 24 saatin en önemli haberleri", "time_expression": "son 24 saat",
                           "open_questions": []},
                          {"restatement": "Son 7 günün en önemli haberleri", "time_expression": "son 24 saat",
                           "open_questions": []})
    conversation_id = _new_conversation(client, auth_headers)

    first = _events(_send(client, auth_headers, conversation_id, "Son 24 saatin en önemli 5 haberi hangileri?"))

    assert "plan" not in _types(first) and "step_started" not in _types(first)
    clarification = next(e for e in first if e["type"] == "clarification")
    question = clarification["questions"][0]
    assert "haber yok" in question["question"]
    assert nodes._local_text(five_days_ago)[:10] in question["question"]
    assert "Son 7 gün" in question["options"]
    assert first[-1]["status"] == "awaiting_clarification"

    second = _events(_send(client, auth_headers, conversation_id, "Son 7 gün"))

    assert next(e for e in second if e["type"] == "intent")["time_range"]["label"] == "Son 7 gün"
    assert "step_started" in _types(second) and second[-1]["status"] == "idle"
    assert _plan_inputs(fake_agent_llm)[0]["veri_kapsamı"]["aralıktaki_haber_sayısı"] == 1


def test_filters_listing_every_known_topic_and_feed_are_dropped(client, auth_headers, db_session, chat_env):
    from tests.conftest import _make_topic
    _make_feed(db_session, "https://example.com/guardian", title="Guardian")
    _make_topic(db_session, "Politika")
    _make_topic(db_session, "Ekonomi")
    chat_env.script("understand", {"restatement": "En önemli haberler", "open_questions": [],
                                   "topics": ["Politika", "Ekonomi"], "feeds": ["DW", "Guardian"]})
    conversation_id = _new_conversation(client, auth_headers)

    _send(client, auth_headers, conversation_id, "En önemli haberler hangileri?")

    intent = _plan_inputs(chat_env)[0]["niyet"]
    assert intent["topics"] == [] and intent["feeds"] == []


def test_an_empty_plan_falls_back_to_the_restatement_not_the_raw_question(client, auth_headers, chat_env):
    chat_env.script("understand", {"restatement": "Son haftanın önem dağılımı", "open_questions": []})
    chat_env.script("plan", {"steps": []})
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "neden böyle?"))

    plan = next(e for e in events if e["type"] == "plan")
    assert [s["goal"] for s in plan["steps"]] == ["Son haftanın önem dağılımı"]


# ---------------------------------------------------------------------------
# Plan approval (Ayarlar › Asistan)
# ---------------------------------------------------------------------------

def test_with_plan_approval_on_the_run_waits_and_starts_on_approval(client, auth_headers, db_session, chat_env):
    crud.set_setting(db_session, "chat_require_plan_approval", "true")
    conversation_id = _new_conversation(client, auth_headers)

    first = _events(_send(client, auth_headers, conversation_id, "Dağılım?"))

    assert "plan_approval" in _types(first) and "step_started" not in _types(first)
    assert first[-1]["status"] == "awaiting_plan_approval"
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["pending"]["kind"] == "plan_approval" and len(detail["pending"]["steps"]) == 1

    second = _events(_send(client, auth_headers, conversation_id, action="approve_plan"))

    assert "step_started" in _types(second) and "plan" not in _types(second)
    assert second[-1]["status"] == "idle"
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["messages"][2] == {**detail["messages"][2], "role": "user", "content": "Planı başlat"}


def test_a_revision_note_replans_and_waits_again(client, auth_headers, db_session, chat_env):
    crud.set_setting(db_session, "chat_require_plan_approval", "true")
    conversation_id = _new_conversation(client, auth_headers)
    _send(client, auth_headers, conversation_id, "Dağılım?")

    revised = _events(_send(client, auth_headers, conversation_id, "Sadece high haberlere bak", action="approve_plan"))

    assert "plan" in _types(revised) and revised[-1]["status"] == "awaiting_plan_approval"
    plan_input = json.loads([c for c in chat_env.calls if c["purpose"] == "plan"][-1]["messages"][1]["content"])
    assert plan_input["kullanıcının_plan_notu"] == "Sadece high haberlere bak"


def test_without_plan_approval_the_plan_runs_directly(client, auth_headers, chat_env):
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Dağılım?"))
    assert "plan_approval" not in _types(events) and "step_started" in _types(events)


# ---------------------------------------------------------------------------
# Reflect: replan, finish early, budget
# ---------------------------------------------------------------------------

def test_reflect_can_replace_the_remaining_steps(client, auth_headers, chat_env):
    chat_env.script("plan", {"steps": [{"goal": "Dar arama", "tool": "sql"}, {"goal": "Gereksiz", "tool": "sql"}]})
    chat_env.script("reflect", {"decision": "replan", "reason": "Sonuç boş",
                                "new_steps": [{"goal": "Geniş arama", "tool": "sql"}]})
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Soru"))

    replan = next(e for e in events if e["type"] == "replan")
    assert [s["goal"] for s in replan["steps"]] == ["Dar arama", "Geniş arama"]
    started = [e["goal"] for e in events if e["type"] == "step_started"]
    assert started == ["Dar arama", "Geniş arama"]


def test_reflect_can_finish_early(client, auth_headers, chat_env):
    chat_env.script("plan", {"steps": [{"goal": "Bir", "tool": "sql"}, {"goal": "İki", "tool": "sql"}]})
    chat_env.script("reflect", {"decision": "finish"})
    conversation_id = _new_conversation(client, auth_headers)
    events = _events(_send(client, auth_headers, conversation_id, "Soru"))
    assert [e["goal"] for e in events if e["type"] == "step_started"] == ["Bir"]
    assert _types(events)[-1] == "done"


def test_the_per_run_budget_stops_the_plan_and_says_so(client, auth_headers, chat_env, monkeypatch):
    monkeypatch.setattr(settings, "chat_max_cost_per_run", 0.05)
    chat_env.cost_per_call = 0.02
    chat_env.script("plan", {"steps": [{"goal": f"Adım {i}", "tool": "sql"} for i in range(1, 4)]})
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Soru"))

    assert len([e for e in events if e["type"] == "step_started"]) < 3
    report_input = json.loads([c for c in chat_env.calls if c["purpose"] == "report"][0]["messages"][1]["content"])
    assert any("bütçe" in note for note in report_input["sınırlamalar"])
    assert events[-1]["cost"] == pytest.approx(sum(0.02 for _ in chat_env.calls))


def test_a_failing_run_reports_an_error_and_frees_the_conversation(client, auth_headers, chat_env, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("OpenAI down")

    from app.services import summary_service
    monkeypatch.setattr(summary_service, "run_agent_llm", broken)
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Soru"))

    assert "error" in _types(events) and events[-1]["status"] == "idle"
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["status"] == "idle" and "tamamlanamadı" in detail["messages"][-1]["content"]


def test_a_failing_run_stores_what_it_already_spent(client, auth_headers, chat_env, monkeypatch):
    chat_env.cost_per_call = 0.01
    real_run = chat_env.run

    async def reflect_breaks(*args, purpose, **kwargs):
        if purpose == "reflect":
            raise RuntimeError("OpenAI down")
        return await real_run(*args, purpose=purpose, **kwargs)

    from app.services import summary_service
    monkeypatch.setattr(summary_service, "run_agent_llm", reflect_breaks)
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Soru"))

    assert "error" in _types(events)
    # understand + plan + execute were billed before reflect failed
    assert events[-1]["cost"] == pytest.approx(0.03)
    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["messages"][-1]["cost"] == pytest.approx(0.03)


def test_a_failure_while_storing_the_turn_still_frees_the_conversation(client, auth_headers, chat_env,
                                                                       monkeypatch):
    real_add = crud.add_chat_message

    def add_breaks_for_the_answer(db, conversation_id, role, *args, **kwargs):
        if role == "assistant":
            raise RuntimeError("DB hiccup")
        return real_add(db, conversation_id, role, *args, **kwargs)

    monkeypatch.setattr(crud, "add_chat_message", add_breaks_for_the_answer)
    conversation_id = _new_conversation(client, auth_headers)

    _events(_send(client, auth_headers, conversation_id, "Soru"))

    detail = client.get(f"/api/chat/conversations/{conversation_id}", headers=auth_headers).json()
    assert detail["status"] == "idle"
    assert _send(client, auth_headers, conversation_id, "Tekrar").status_code == 200


def test_parallel_tool_calls_beyond_the_step_limit_are_not_run(client, auth_headers, chat_env, monkeypatch):
    monkeypatch.setattr(settings, "chat_max_tool_calls_per_step", 2)
    query = json.dumps({"query": "SELECT count(*) FROM chat_articles"})
    calls = [{"id": f"call_{i}", "name": "run_sql", "arguments": query} for i in range(4)]
    chat_env.script("execute", {"tool_calls": calls}, "Bulgu.")
    conversation_id = _new_conversation(client, auth_headers)

    events = _events(_send(client, auth_headers, conversation_id, "Soru"))

    assert len([e for e in events if e["type"] == "tool_call"]) == 2
    execute = [c for c in chat_env.calls if c["purpose"] == "execute"][1]
    assistant = next(m for m in execute["messages"] if m["role"] == "assistant")
    tool_replies = [m for m in execute["messages"] if m["role"] == "tool"]
    # Every tool_call the model is shown has exactly one reply (the API rejects anything else).
    assert [c["id"] for c in assistant["tool_calls"]] == [m["tool_call_id"] for m in tool_replies]


def test_startup_frees_conversations_left_running(db_session, test_user):
    conversation = crud.create_chat_conversation(db_session, test_user.id, "x")
    crud.update_chat_conversation(db_session, conversation.id, status="running")
    assert crud.reset_running_chat_conversations(db_session) == 1
    db_session.refresh(conversation)
    assert conversation.status == "idle"


# ---------------------------------------------------------------------------
# Tools endpoint + settings
# ---------------------------------------------------------------------------

def test_tools_endpoint_reports_availability_and_state(client, auth_headers, db_session):
    crud.set_setting(db_session, "chat_enabled_tools", "sql,semantic_search")
    tools = {t["name"]: t for t in client.get("/api/chat/tools", headers=auth_headers).json()}
    assert tools["sql"]["available"] and tools["sql"]["enabled"] and tools["sql"]["active"]
    assert not tools["chart"]["enabled"] and not tools["chart"]["active"]
    assert not tools["semantic_search"]["available"] and tools["semantic_search"]["unavailable_reason"]
    assert tools["semantic_search"]["enabled"] and not tools["semantic_search"]["active"]


def test_settings_save_and_return_the_chat_options(client, admin_headers, db_session):
    response = client.put("/api/settings/", json={"chat_enabled_tools": "chart, sql",
                                                   "chat_require_plan_approval": True}, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["chat_enabled_tools"] == "sql,chart" and body["chat_require_plan_approval"] is True
    assert crud.get_setting(db_session, "chat_enabled_tools") == "sql,chart"


@pytest.mark.parametrize("value", ["sql,bogus", "chart", "semantic_search,chart"])
def test_settings_reject_unknown_tools_or_no_usable_data_tool(client, admin_headers, value):
    response = client.put("/api/settings/", json={"chat_enabled_tools": value}, headers=admin_headers)
    assert response.status_code == 422


def test_chat_settings_require_admin(client, auth_headers):
    response = client.put("/api/settings/", json={"chat_require_plan_approval": True}, headers=auth_headers)
    assert response.status_code == 403
