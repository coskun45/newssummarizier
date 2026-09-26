"""
Tests for app/api/routes/playground.py — pipeline settings + non-persisting dry run.

The OpenAI client is replaced by a recording fake, so the real _run_classification/_run_summary
code (prompt building, retry, JSON parsing) is exercised without any network access.
"""
import json
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.exceptions import CostLimitExceededError
from app.db import crud, models
from app.services import summary_service
from tests.conftest import _make_feed, _make_article, _make_topic

IMPORTANT = json.dumps({
    "importance": "important",
    "priority": "high",
    "topics": [{"name": "NATO", "confidence": 0.9}, {"name": "Ghost Topic", "confidence": 0.6}],
})
UNIMPORTANT = json.dumps({"importance": "unimportant", "priority": None, "topics": []})


def _is_summary_call(kwargs) -> bool:
    # Both calls use JSON mode now; only the summary call sends the article content.
    return "<article_content>" in kwargs["messages"][-1]["content"]


class FakeOpenAI:
    """Records every chat.completions.create call; `responder(kwargs)` returns the message content."""

    def __init__(self, responder):
        self.calls = []
        self._responder = responder
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        content = self._responder(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=SimpleNamespace(completion_tokens=7),
        )

    @property
    def classification_calls(self):
        return [c for c in self.calls if not _is_summary_call(c)]

    @property
    def summary_calls(self):
        return [c for c in self.calls if _is_summary_call(c)]


def _install(monkeypatch, db_session, classification=IMPORTANT, summary=lambda kw: "Özet metni"):
    """Patch OpenAI + DB session plumbing; return the fake client."""
    from sqlalchemy.orm import sessionmaker

    def responder(kwargs):
        if not _is_summary_call(kwargs):
            return classification(kwargs) if callable(classification) else classification
        return summary(kwargs)

    fake = FakeOpenAI(responder)
    monkeypatch.setattr(summary_service, "get_openai_client", lambda: fake)
    monkeypatch.setattr(summary_service, "SessionLocal",
                        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False))
    return fake


@pytest.fixture
def article(db_session):
    feed = _make_feed(db_session)
    _make_topic(db_session, "NATO", description="Bündnis")
    return _make_article(db_session, feed.id, title="NATO erweitert Präsenz",
                         cleaned_content="Langer Artikeltext über die NATO.")


def _row_counts(db_session):
    return {
        "summaries": db_session.query(models.Summary).count(),
        "logs": db_session.query(models.ProcessingLog).count(),
        "article_topics": db_session.query(models.ArticleTopic).count(),
        "articles": db_session.query(models.Article).count(),
    }


# --- auth / validation -------------------------------------------------------------------

def test_playground_requires_auth(client):
    assert client.get("/api/playground/settings").status_code == 401
    assert client.post("/api/playground/run", json={"article_id": 1}).status_code == 401


def test_run_unknown_article_is_404(client, admin_headers, monkeypatch, db_session):
    _install(monkeypatch, db_session)
    response = client.post("/api/playground/run", json={"article_id": 999}, headers=admin_headers)
    assert response.status_code == 404


@pytest.mark.parametrize("payload", [
    {"stages": ["nope"]},
    {"stages": []},
    {"summary_types": ["huge"]},
    {"summary_instructions": {"huge": "x"}},
])
def test_run_rejects_bad_input(client, admin_headers, monkeypatch, db_session, article, payload):
    fake = _install(monkeypatch, db_session)
    response = client.post("/api/playground/run", json={"article_id": article.id, **payload}, headers=admin_headers)
    assert response.status_code == 400
    assert fake.calls == []


def test_run_summarization_needs_article_content(client, admin_headers, monkeypatch, db_session):
    fake = _install(monkeypatch, db_session)
    empty = _make_article(db_session, _make_feed(db_session, url="https://e.com/f2").id, title="Leer")

    response = client.post("/api/playground/run",
                           json={"article_id": empty.id, "stages": ["summarization"]}, headers=admin_headers)
    assert response.status_code == 400
    assert fake.calls == []

    # Classification only needs the title, so it still works.
    response = client.post("/api/playground/run",
                           json={"article_id": empty.id, "stages": ["classification"]}, headers=admin_headers)
    assert response.status_code == 200


def test_run_cost_limit_is_429(client, admin_headers, monkeypatch, db_session, article):
    _install(monkeypatch, db_session)

    async def over_limit():
        raise CostLimitExceededError("Daily cost limit exceeded")

    monkeypatch.setattr(summary_service, "check_cost_limits", over_limit)
    response = client.post("/api/playground/run", json={"article_id": article.id}, headers=admin_headers)
    assert response.status_code == 429


# --- settings ----------------------------------------------------------------------------

def test_settings_report_models_prompts_and_topics(client, auth_headers, db_session, article):
    body = client.get("/api/playground/settings", headers=auth_headers).json()

    assert body["classification_model"] == settings.default_model
    assert body["classification_prompt"]["source"] == "default"
    # The editable text carries only the criteria; the topic list + output format are locked.
    assert "{topic_list}" not in body["classification_prompt"]["text"]
    assert "- NATO: Bündnis" not in body["classification_prompt"]["text"]
    locked = body["classification_locked_text"]
    assert "- NATO: Bündnis" in locked and '"importance"' in locked and "JSON" in locked
    assert body["summarization_prompt"]["source"] == "default"
    locked = body["summarization_locked"]
    assert locked["heading"] and summary_service.SUMMARY_LANGUAGE_INSTRUCTION in locked["language_line"]
    by_type = {t["type"]: t for t in body["summary_types"]}
    assert by_type["detailed"]["model"] == settings.detailed_model
    assert by_type["brief"]["max_tokens"] == settings.max_tokens_output_brief
    assert all(t["enabled"] for t in by_type.values())
    assert {"name": "NATO", "description": "Bündnis"} in body["topics"]


def test_settings_prefer_active_db_prompt_and_enabled_types(client, auth_headers, db_session):
    crud.upsert_system_prompt(db_session, "classification", "DB classification", True)
    crud.upsert_system_prompt(db_session, "summarization", "DB summarization", False)
    crud.set_setting(db_session, "enabled_summary_types", "brief")

    body = client.get("/api/playground/settings", headers=auth_headers).json()

    assert body["classification_prompt"] == {"text": "DB classification", "source": "db"}
    assert body["summarization_prompt"]["source"] == "default"  # inactive DB prompt is ignored
    assert {t["type"]: t["enabled"] for t in body["summary_types"]} == {
        "brief": True, "standard": False, "detailed": False,
    }


# --- run ---------------------------------------------------------------------------------

def test_run_returns_stage_details_and_persists_nothing(client, admin_headers, monkeypatch, db_session, article):
    fake = _install(monkeypatch, db_session)
    before = _row_counts(db_session)

    response = client.post("/api/playground/run", json={"article_id": article.id}, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["article"]["id"] == article.id
    assert body["content_used"] == {"source": "cleaned", "chars": len(article.cleaned_content),
                                    "used_chars": len(article.cleaned_content), "truncated": False}

    cls = body["classification"]
    assert (cls["importance"], cls["priority"], cls["pipeline_outcome"]) == ("important", "high", "continue")
    assert cls["prompt_source"] == "default"
    assert cls["model"] == settings.default_model
    assert len(cls["attempts"]) == 1 and cls["attempts"][0]["raw_response"] == IMPORTANT
    assert {t["name"]: t["known"] for t in cls["topics"]} == {"NATO": True, "Ghost Topic": False}
    assert "NATO erweitert Präsenz" in cls["attempts"][0]["user_prompt"]

    assert [s["summary_type"] for s in body["summaries"]] == ["brief", "standard", "detailed"]
    detailed = body["summaries"][2]
    assert detailed["model"] == settings.detailed_model
    assert detailed["summary_text"] == "Özet metni"
    assert detailed["tokens_used"] == detailed["input_tokens"] + detailed["output_tokens"]
    assert body["total_cost"] == pytest.approx(cls["cost"] + sum(s["cost"] for s in body["summaries"]))
    assert len(fake.classification_calls) == 1 and len(fake.summary_calls) == 3

    # Dry run: no rows written and the article itself is untouched...
    assert _row_counts(db_session) == before
    # ...but the OpenAI spend still counts towards the cost limits (#25).
    assert crud.get_daily_cost(db_session) == pytest.approx(body["total_cost"])
    db_session.refresh(article)
    assert (article.importance, article.priority, article.status) == (None, None, "pending")


def test_run_uses_prompt_overrides_for_this_call_only(client, admin_headers, monkeypatch, db_session, article):
    fake = _install(monkeypatch, db_session)
    crud.upsert_system_prompt(db_session, "classification", "DB classification", True)

    response = client.post("/api/playground/run", json={
        "article_id": article.id,
        "classification_prompt": "OVERRIDE CLS.",
        "summarization_prompt": "OVERRIDE SUM",
        "summary_types": ["brief"],
        "summary_instructions": {"brief": "Nur ein Satz."},
    }, headers=admin_headers)

    body = response.json()
    cls_system = fake.classification_calls[0]["messages"][0]["content"]
    # The override has no {topic_list}/format text, yet the locked block is still appended.
    assert cls_system.startswith("OVERRIDE CLS.") and "- NATO: Bündnis" in cls_system
    assert '"importance": "unimportant"' in cls_system and "confidence >= 0.5" in cls_system
    assert body["classification"]["system_prompt"] == cls_system
    assert body["classification"]["prompt_source"] == "override"
    assert len(fake.summary_calls) == 1
    assert fake.summary_calls[0]["messages"][0]["content"] == "OVERRIDE SUM"
    assert "Instructions: Nur ein Satz." in fake.summary_calls[0]["messages"][1]["content"]
    assert body["summaries"][0]["instructions"] == "Nur ein Satz."
    assert body["summaries"][0]["prompt_source"] == "override"

    # The stored prompt was not modified by the override.
    assert crud.get_system_prompt(db_session, "classification").prompt_text == "DB classification"


def test_run_skips_summaries_for_unimportant_unless_forced(client, admin_headers, monkeypatch, db_session, article):
    fake = _install(monkeypatch, db_session, classification=UNIMPORTANT)

    body = client.post("/api/playground/run", json={"article_id": article.id}, headers=admin_headers).json()
    assert body["classification"]["pipeline_outcome"] == "filtered"
    assert body["skipped_reason"] == "unimportant"
    assert body["summaries"] == [] and fake.summary_calls == []

    body = client.post("/api/playground/run",
                       json={"article_id": article.id, "force_summarize": True}, headers=admin_headers).json()
    assert body["skipped_reason"] is None
    assert len(body["summaries"]) == 3


def test_run_single_stage_only_calls_that_stage(client, admin_headers, monkeypatch, db_session, article):
    fake = _install(monkeypatch, db_session, classification=UNIMPORTANT)

    body = client.post("/api/playground/run",
                       json={"article_id": article.id, "stages": ["summarization"]}, headers=admin_headers).json()

    assert body["classification"] is None
    assert fake.classification_calls == []
    assert len(body["summaries"]) == 3  # no classification in this run → nothing to skip on


def test_run_invalid_json_is_retried_then_reported_as_failed(client, admin_headers, monkeypatch, db_session, article):
    fake = _install(monkeypatch, db_session, classification="not json at all")

    body = client.post("/api/playground/run", json={"article_id": article.id}, headers=admin_headers).json()

    cls = body["classification"]
    assert len(cls["attempts"]) == 2 and len(fake.classification_calls) == 2
    assert "JSON" in cls["attempts"][0]["error"]
    assert cls["error"] and cls["pipeline_outcome"] == "failed"
    assert cls["attempts"][1]["raw_response"] == "not json at all"
    assert body["skipped_reason"] == "classification_failed" and body["summaries"] == []


def test_run_important_without_priority_is_flagged_failed(client, admin_headers, monkeypatch, db_session, article):
    _install(monkeypatch, db_session, classification=json.dumps({"importance": "important", "priority": None, "topics": []}))

    body = client.post("/api/playground/run",
                       json={"article_id": article.id, "stages": ["classification"]}, headers=admin_headers).json()

    assert body["classification"]["pipeline_outcome"] == "failed"
    assert "priority" in body["classification"]["error"]


def test_run_one_failing_summary_type_does_not_hide_the_others(client, admin_headers, monkeypatch, db_session, article):
    detailed_marker = summary_service.DEFAULT_SUMMARY_INSTRUCTIONS["detailed"]

    def summary(kwargs):
        if detailed_marker in kwargs["messages"][1]["content"]:
            raise RuntimeError("boom")
        return "ok"

    _install(monkeypatch, db_session, summary=summary)

    body = client.post("/api/playground/run", json={"article_id": article.id}, headers=admin_headers).json()

    by_type = {s["summary_type"]: s for s in body["summaries"]}
    assert by_type["brief"]["summary_text"] == "ok" and by_type["brief"]["error"] is None
    assert by_type["detailed"]["summary_text"] is None and "boom" in by_type["detailed"]["error"]


def test_run_reports_truncation_of_long_content(client, admin_headers, monkeypatch, db_session):
    _install(monkeypatch, db_session)
    long_article = _make_article(db_session, _make_feed(db_session, url="https://e.com/f3").id,
                                 title="Lang", raw_content="x" * 50000)

    body = client.post("/api/playground/run",
                       json={"article_id": long_article.id, "stages": ["summarization"], "summary_types": ["brief"]},
                       headers=admin_headers).json()

    assert body["content_used"]["source"] == "raw"
    assert body["content_used"]["truncated"] is True
    assert body["content_used"]["used_chars"] < body["content_used"]["chars"]


def test_run_truncation_flag_is_set_when_only_the_ellipsis_marker_is_added(client, admin_headers, monkeypatch, db_session):
    # truncate_content() cuts at max_tokens*4 chars and appends "...", so content that is only a
    # character or two over the limit ends up the same length or longer after truncation.
    _install(monkeypatch, db_session)
    limit = 4000 * 4
    barely_long = _make_article(db_session, _make_feed(db_session, url="https://e.com/f4").id,
                                title="Knapp", raw_content="y" * (limit + 1))

    body = client.post("/api/playground/run",
                       json={"article_id": barely_long.id, "stages": ["summarization"], "summary_types": ["brief"]},
                       headers=admin_headers).json()

    assert body["content_used"]["truncated"] is True


def test_run_malformed_model_field_types_do_not_break_the_response(client, admin_headers, monkeypatch, db_session, article):
    malformed = json.dumps({"importance": "important", "priority": 3,
                            "topics": [{"name": "NATO", "confidence": "very high"}]})
    _install(monkeypatch, db_session, classification=malformed)

    response = client.post("/api/playground/run",
                           json={"article_id": article.id, "stages": ["classification"]}, headers=admin_headers)

    assert response.status_code == 200
    cls = response.json()["classification"]
    assert cls["pipeline_outcome"] == "failed"
    assert cls["topics"] == [{"name": "NATO", "confidence": None, "known": True}]


def test_run_json_null_reply_is_retried_and_flagged(client, admin_headers, monkeypatch, db_session, article):
    replies = iter(["null", IMPORTANT])
    fake = _install(monkeypatch, db_session, classification=lambda kw: next(replies))

    body = client.post("/api/playground/run",
                       json={"article_id": article.id, "stages": ["classification"]}, headers=admin_headers).json()

    cls = body["classification"]
    assert len(fake.classification_calls) == 2
    assert "null" in cls["attempts"][0]["error"].lower()
    assert cls["attempts"][1]["error"] is None
    assert cls["pipeline_outcome"] == "continue"


def test_run_null_reply_twice_reports_an_error_instead_of_a_silent_failure(client, admin_headers, monkeypatch, db_session, article):
    _install(monkeypatch, db_session, classification="null")

    cls = client.post("/api/playground/run",
                      json={"article_id": article.id, "stages": ["classification"]}, headers=admin_headers).json()["classification"]

    assert cls["pipeline_outcome"] == "failed"
    assert cls["error"]


def test_run_api_error_on_retry_keeps_the_first_attempt(client, admin_headers, monkeypatch, db_session, article):
    calls = []

    def classification(kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return "not json"
        raise RuntimeError("upstream timeout")

    _install(monkeypatch, db_session, classification=classification)

    body = client.post("/api/playground/run",
                       json={"article_id": article.id, "stages": ["classification"]}, headers=admin_headers).json()

    cls = body["classification"]
    assert [a["raw_response"] for a in cls["attempts"]] == ["not json", None]
    assert "upstream timeout" in cls["attempts"][1]["error"]
    assert cls["error"] and "upstream timeout" in cls["error"]
    assert cls["pipeline_outcome"] == "failed"
    assert cls["cost"] > 0 and body["total_cost"] == pytest.approx(cls["cost"])


def test_run_sends_feed_name_as_source_and_returns_the_model_author(client, admin_headers, monkeypatch, db_session):
    feed = _make_feed(db_session, url="https://example.com/aa", title="Anadolu Ajansı")
    art = _make_article(db_session, feed.id, cleaned_content="ANKARA (AA) - ...", author="Anadolu Ajansı")
    fake = _install(monkeypatch, db_session,
                    summary=lambda kw: '{"summary": "📌 Anadolu Ajansı / Burak Bir - X", "author": "Burak Bir"}')
    before = _row_counts(db_session)

    body = client.post("/api/playground/run", json={
        "article_id": art.id, "stages": ["summarization"], "summary_types": ["brief"],
    }, headers=admin_headers).json()

    user = fake.summary_calls[0]["messages"][1]["content"]
    assert "<article_source>\nAnadolu Ajansı\n</article_source>" in user
    assert "<author_hint>\n-\n</author_hint>" in user  # the org name is not passed as an author
    assert body["summaries"][0]["summary_text"] == "📌 Anadolu Ajansı / Burak Bir - X"
    assert body["summaries"][0]["author"] == "Burak Bir"
    db_session.expire_all()
    assert _row_counts(db_session) == before and art.author == "Anadolu Ajansı"  # dry run


def test_run_uses_the_feed_author_as_hint_even_after_the_pipeline_cleared_it(client, admin_headers, monkeypatch, db_session):
    feed = _make_feed(db_session, url="https://example.com/dw", title="DW Türkçe")
    art = _make_article(db_session, feed.id, cleaned_content="text", author="Max Bird")
    crud.set_article_author(db_session, art.id, None)  # what a pipeline run with "no author" leaves
    fake = _install(monkeypatch, db_session)

    client.post("/api/playground/run", json={
        "article_id": art.id, "stages": ["summarization"], "summary_types": ["brief"],
    }, headers=admin_headers)

    assert "<author_hint>\nMax Bird\n</author_hint>" in fake.summary_calls[0]["messages"][1]["content"]
