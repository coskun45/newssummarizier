"""
Regression (#25): the cost limits only summed `Summary.cost`, so classification, bulletin and
Playground calls were never counted, and a summary's cost vanished when it was replaced or its
article deleted. Every OpenAI call is now recorded in `llm_usage`, with the token counts the API
reports.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db import crud
from app.services import bulletin_service, summary_service
from tests.conftest import _make_article, _make_feed, _make_summary

PROMPT_TOKENS, COMPLETION_TOKENS = 1234, 56


class FakeOpenAI:
    def __init__(self, content):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self._content = content

    async def _create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._content), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=PROMPT_TOKENS, completion_tokens=COMPLETION_TOKENS),
        )


@pytest.fixture
def llm(monkeypatch, db_session):
    monkeypatch.setattr(summary_service, "SessionLocal", sessionmaker(bind=db_session.get_bind()))

    def install(content):
        for module in (summary_service, bulletin_service):
            monkeypatch.setattr(module, "get_openai_client", lambda: FakeOpenAI(content))

    return install


def _expected(model):
    return summary_service.calculate_cost(model, PROMPT_TOKENS, COMPLETION_TOKENS)


def test_classification_cost_counts_towards_the_limits(llm, db_session):
    llm(json.dumps({"importance": "unimportant", "priority": None, "topics": []}))

    asyncio.run(summary_service.categorize_and_prioritize_article("Başlık"))

    # the API's own prompt_tokens, not a tiktoken estimate
    assert crud.get_daily_cost(db_session) == pytest.approx(_expected(settings.default_model))


def test_failed_classification_is_still_billed(llm, db_session):
    llm("not json at all")

    with pytest.raises(Exception):
        asyncio.run(summary_service.categorize_and_prioritize_article("Başlık"))

    assert crud.get_daily_cost(db_session) == pytest.approx(2 * _expected(settings.default_model))  # + retry


def test_summary_cost_survives_its_article_being_deleted(llm, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    llm(json.dumps({"summary": "Özet", "author": None}))

    result = asyncio.run(summary_service.generate_summary("Başlık", "metin", "detailed"))
    assert result["tokens_used"] == PROMPT_TOKENS + COMPLETION_TOKENS
    crud.delete_article(db_session, article.id)

    assert crud.get_monthly_cost(db_session) == pytest.approx(_expected(settings.detailed_model))


def test_bulletin_calls_count_towards_the_limits(llm, db_session):
    llm(json.dumps({"classifications": []}))

    asyncio.run(bulletin_service._call_json_completion("system", "user", max_completion_tokens=100))

    assert crud.get_daily_cost(db_session) == pytest.approx(_expected(settings.default_model))


def test_existing_summary_costs_are_backfilled_once(db_session):
    """Costs recorded before `llm_usage` existed keep counting towards this month's limit."""
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id)
    _make_summary(db_session, article.id, cost=0.25)
    _make_summary(db_session, article.id, summary_type="brief", cost=0.5)

    assert crud.backfill_llm_usage_from_summaries(db_session) == 2
    assert crud.backfill_llm_usage_from_summaries(db_session) == 0  # idempotent
    assert crud.get_monthly_cost(db_session) == pytest.approx(0.75)
