"""
Free-source match for blocked / paywalled articles (summary_service.find_free_alternative, the
candidate query crud.free_match_candidates and the 21:00 re-check task). OpenAI is faked: the
embeddings count a few keywords (so similarity is predictable) and the confirming model answers
what the test scripts.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db import crud, database
from app.services import summary_service
from tests.conftest import _make_article, _make_feed

# conftest stubs find_free_alternative for every test; these tests exercise the real one.
REAL_FIND = summary_service.find_free_alternative

KEYWORDS = (("gaza",), ("nvidia", "huang"), ("wahl", "election", "seçim"))


def keyword_vector(text):
    lowered = text.lower()
    return [float(sum(lowered.count(word) for word in group)) for group in KEYWORDS] + [0.1]


class FakeOpenAI:
    def __init__(self):
        self.embedding_calls = []
        self.chat_calls = []
        self.answer = {"match": 1}
        self.embeddings = SimpleNamespace(create=self._embed)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))

    async def _embed(self, model, input, dimensions):
        self.embedding_calls.append(list(input))
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=keyword_vector(t)) for i, t in enumerate(input)],
            usage=SimpleNamespace(total_tokens=5 * len(input)),
        )

    async def _chat(self, model, messages, **kwargs):
        self.chat_calls.append(messages[-1]["content"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(self.answer)),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5),
        )


@pytest.fixture()
def openai(monkeypatch, agent_db):
    monkeypatch.setitem(database.vector_support, "available", True)
    fake = FakeOpenAI()
    monkeypatch.setattr(summary_service, "get_openai_client", lambda: fake)
    return fake


NOW = datetime.now(timezone.utc)


def _free_article(db_session, feed, title, content, published_at=NOW):
    """A summarized, fully read article of a free feed, embedded like the pipeline does."""
    article = _make_article(db_session, feed.id, title=title, status="summarized",
                            cleaned_content=content, published_at=published_at)
    asyncio.run(summary_service.embed_article(db_session, article.id))
    return article


def _blocked_article(db_session, feed, title="Palestinians flock back to northern Gaza"):
    return _make_article(db_session, feed.id, title=title, status="summarized", published_at=NOW,
                         raw_content="<p>Teaser.</p>")


def _run(db_session, article_id):
    cost = asyncio.run(REAL_FIND(db_session, article_id))
    db_session.expire_all()
    return crud.get_article(db_session, article_id), cost


@pytest.fixture()
def feeds(db_session):
    return SimpleNamespace(
        paid=_make_feed(db_session, "https://wsj.example/feed", title="WSJ"),
        free=_make_feed(db_session, "https://dw.example/feed", title="DW"),
    )


def test_same_story_in_a_free_source_is_linked(db_session, openai, feeds):
    match = _free_article(db_session, feeds.free, "Gazze'nin kuzeyine dönüş", "Gaza Gaza haberi metni.")
    _free_article(db_session, feeds.free, "Nvidia'nın Huang'ı Çin'de", "Nvidia Huang metni.")
    blocked = _blocked_article(db_session, feeds.paid)

    article, cost = _run(db_session, blocked.id)

    assert article.content_access == "free_match"
    assert article.free_match_article_id == match.id
    assert article.free_match_checked_at is not None
    assert cost > 0
    # Only the close candidate was offered to the model.
    assert "Gazze" in openai.chat_calls[0] and "Nvidia" not in openai.chat_calls[0]


def test_model_saying_none_leaves_the_article_unavailable(db_session, openai, feeds):
    _free_article(db_session, feeds.free, "Gazze'de başka bir olay", "Gaza metni.")
    openai.answer = {"match": None}
    blocked = _blocked_article(db_session, feeds.paid)

    article, _ = _run(db_session, blocked.id)

    assert article.content_access == "unavailable"
    assert article.free_match_article_id is None


@pytest.mark.parametrize("answer", [{"match": 7}, {"match": "1"}, {}])
def test_an_invalid_model_answer_is_no_match(db_session, openai, feeds, answer):
    _free_article(db_session, feeds.free, "Gazze", "Gaza metni.")
    openai.answer = answer
    blocked = _blocked_article(db_session, feeds.paid)

    assert _run(db_session, blocked.id)[0].content_access == "unavailable"


def test_no_close_candidate_skips_the_model(db_session, openai, feeds):
    _free_article(db_session, feeds.free, "Seçim sonuçları", "Wahl election metni.")
    blocked = _blocked_article(db_session, feeds.paid)

    article, _ = _run(db_session, blocked.id)

    assert article.content_access == "unavailable"
    assert openai.chat_calls == []


def test_candidates_exclude_same_feed_old_and_blocked_articles(db_session, openai, feeds):
    other_free = _make_feed(db_session, "https://bbc.example/feed", title="BBC")
    _free_article(db_session, feeds.paid, "WSJ'nin kendi Gazze haberi", "Gaza metni.")  # same feed
    _free_article(db_session, feeds.free, "Eski Gazze haberi", "Gaza metni.",
                  published_at=NOW - timedelta(days=5))  # outside the window
    paywalled = _free_article(db_session, other_free, "Ücretli Gazze haberi", "Gaza metni.")
    crud.set_article_content_access(db_session, paywalled.id, "unavailable")  # itself blocked
    blocked = _blocked_article(db_session, feeds.paid)

    article, _ = _run(db_session, blocked.id)

    assert article.content_access == "unavailable"
    assert openai.chat_calls == []


def test_without_pgvector_nothing_is_searched_and_no_label_is_claimed(db_session, openai, feeds, monkeypatch):
    """Regression (review): without pgvector nothing was searched, yet the card said "İçerik
    alınamadı" with the tooltip "no free source has the same story"."""
    _free_article(db_session, feeds.free, "Gazze", "Gaza metni.")
    monkeypatch.setitem(database.vector_support, "available", False)
    openai.embedding_calls.clear()
    blocked = _blocked_article(db_session, feeds.paid)

    article, cost = _run(db_session, blocked.id)

    assert article.content_access is None
    assert (openai.embedding_calls, openai.chat_calls, cost) == ([], [], 0.0)


def test_an_api_error_never_raises_and_labels_unavailable(db_session, openai, feeds):
    async def down(**kwargs):
        raise RuntimeError("embeddings down")

    openai.embeddings = SimpleNamespace(create=down)
    blocked = _blocked_article(db_session, feeds.paid)

    article, _ = _run(db_session, blocked.id)

    assert article.content_access == "unavailable"


def test_crawl_failed_rule():
    assert summary_service.crawl_failed(None, False)
    assert summary_service.crawl_failed("   ", False)
    assert summary_service.crawl_failed("Kurzer Vorspann.", True)
    assert not summary_service.crawl_failed("Kurzer, aber freier Text.", False)
    assert not summary_service.crawl_failed("x" * 1500, True)


def test_recheck_task_searches_only_recent_unavailable_articles(db_session, agent_db, feeds, monkeypatch):
    from app.tasks import background

    recent = _blocked_article(db_session, feeds.paid)
    crud.set_article_content_access(db_session, recent.id, "unavailable")
    matched = _blocked_article(db_session, feeds.paid, title="Başka")
    crud.set_article_content_access(db_session, matched.id, "free_match", recent.id)
    old = _blocked_article(db_session, feeds.paid, title="Eski")
    crud.set_article_content_access(db_session, old.id, "unavailable")
    old.fetched_at = NOW - timedelta(hours=30)
    db_session.commit()
    searched = []

    async def fake_find(db, article_id):
        searched.append(article_id)
        return 0.0

    monkeypatch.setattr(summary_service, "find_free_alternative", fake_find)

    asyncio.run(background.recheck_free_alternatives_task())

    assert searched == [recent.id]


def test_deleting_the_matched_article_clears_the_link(db_session, feeds):
    free = _make_article(db_session, feeds.free.id, title="Ücretsiz", status="summarized")
    blocked = _blocked_article(db_session, feeds.paid)
    crud.set_article_content_access(db_session, blocked.id, "free_match", free.id)

    assert crud.delete_article(db_session, free.id)

    db_session.expire_all()
    assert crud.get_article(db_session, blocked.id).free_match_article_id is None


def test_recheck_task_also_searches_a_free_match_whose_match_was_deleted(db_session, agent_db, feeds, monkeypatch):
    """Regression (review): deleting the matched article NULLs the link but left content_access
    "free_match" — the card said "Ücretsiz kaynakta var" without a link and the 21:00 re-check
    (only "unavailable") never looked at it again."""
    from app.tasks import background

    free = _make_article(db_session, feeds.free.id, title="Ücretsiz", status="summarized")
    orphaned = _blocked_article(db_session, feeds.paid)
    crud.set_article_content_access(db_session, orphaned.id, "free_match", free.id)
    crud.delete_article(db_session, free.id)
    searched = []

    async def fake_find(db, article_id):
        searched.append(article_id)
        return 0.0

    monkeypatch.setattr(summary_service, "find_free_alternative", fake_find)

    asyncio.run(background.recheck_free_alternatives_task())

    assert searched == [orphaned.id]
