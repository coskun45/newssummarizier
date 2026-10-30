"""
Tests for vector search: embedding articles' full text in chunks (summary_service.embed_article,
the pipeline step and the backfill), the hybrid search (crud.semantic_candidates + tools.fuse_rankings + the
semantic_search tool) and the status/backfill endpoints. OpenAI is a fake embeddings client whose
vectors count a few keywords, so similarity is predictable.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.agents.analysis import tools
from app.db import crud, database, models
from app.services import summary_service
from tests.conftest import _make_article, _make_feed, _make_summary

KEYWORDS = (("energie", "enerji", "energy"), ("wahl", "seçim", "election"), ("krieg", "savaş", "war"))


def keyword_vector(text):
    lowered = text.lower()
    return [float(sum(lowered.count(word) for word in group)) for group in KEYWORDS] + [0.1]


class FakeEmbeddings:
    def __init__(self):
        self.calls = []
        self.fail = False

    async def create(self, model, input, dimensions):
        if self.fail:
            raise RuntimeError("embeddings down")
        self.calls.append(list(input))
        return SimpleNamespace(
            data=[SimpleNamespace(index=i, embedding=keyword_vector(text)) for i, text in enumerate(input)],
            usage=SimpleNamespace(total_tokens=10 * len(input)),
        )


@pytest.fixture()
def vectors(monkeypatch, agent_db):
    """pgvector "available" (SQLite computes similarity in Python) and a fake embeddings API."""
    monkeypatch.setitem(database.vector_support, "available", True)
    monkeypatch.setitem(database.vector_support, "reason", None)
    fake = FakeEmbeddings()
    monkeypatch.setattr(summary_service, "get_openai_client", lambda: SimpleNamespace(embeddings=fake))
    return fake


def _summarized(db_session, feed, title, summary, content="", priority="high"):
    article = _make_article(db_session, feed.id, title=title, priority=priority, status="summarized",
                            cleaned_content=content)
    _make_summary(db_session, article.id, summary_type="standard", summary_text=summary)
    return article


def _embed(db_session, article_id):
    return asyncio.run(summary_service.embed_article(db_session, article_id))


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_chunk_text_splits_with_overlap():
    encoding = summary_service._embedding_encoding()
    text = " ".join(f"kelime{i}" for i in range(500))
    chunks = summary_service.chunk_text(text, max_tokens=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(encoding.encode(c)) <= 100 for c in chunks)
    # Consecutive chunks share their border tokens.
    assert encoding.encode(chunks[0])[-20:] == encoding.encode(chunks[1])[:20]
    assert summary_service.chunk_text("", 100, 20) == []


# ---------------------------------------------------------------------------
# embed_article
# ---------------------------------------------------------------------------

def test_a_summarized_article_gets_its_full_text_embedded_in_chunks(vectors, db_session, monkeypatch):
    monkeypatch.setattr(summary_service.settings, "embedding_chunk_tokens", 20)
    monkeypatch.setattr(summary_service.settings, "embedding_chunk_overlap", 5)
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "Energiekrise", "Enerji krizi derinleşiyor.",
                          content=" ".join(["Die Energiekrise trifft Europa hart."] * 12))

    outcome = _embed(db_session, article.id)

    assert outcome["chunks"] > 1
    chunks = (db_session.query(models.ArticleChunkEmbedding).filter_by(article_id=article.id)
              .order_by(models.ArticleChunkEmbedding.chunk_index).all())
    assert len(chunks) == outcome["chunks"] and [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[0].model == summary_service.settings.embedding_model
    # Each chunk is embedded with the title in front; the summary itself is not embedded.
    assert vectors.calls[0][0] == f"Energiekrise\n\n{chunks[0].text}"
    assert chunks[0].embedding == keyword_vector(f"Energiekrise\n\n{chunks[0].text}")
    assert not any("derinleşiyor" in text for text in vectors.calls[0])
    usage = db_session.query(models.LlmUsage).one()
    assert usage.kind == "embedding" and usage.article_id == article.id and usage.cost > 0


def test_embedding_again_is_free_until_the_text_changes(vectors, db_session):
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "T", "Özet bir.", content="Inhalt eins.")
    _embed(db_session, article.id)
    assert _embed(db_session, article.id) == {"chunks": 0, "cost": 0.0}

    summary = db_session.query(models.Summary).filter_by(article_id=article.id).one()
    summary.summary_text = "Özet iki."
    db_session.commit()
    assert _embed(db_session, article.id)["chunks"] == 0  # a new summary doesn't matter
    assert len(vectors.calls) == 1

    article.cleaned_content = "Inhalt zwei (Wahl)."
    db_session.commit()
    outcome = _embed(db_session, article.id)

    assert outcome["chunks"] == 1
    assert vectors.calls[-1] == ["T\n\nInhalt zwei (Wahl)."]
    texts = [c.text for c in db_session.query(models.ArticleChunkEmbedding).filter_by(article_id=article.id)]
    assert texts == ["Inhalt zwei (Wahl)."]  # the old chunks were replaced


@pytest.mark.parametrize("status", ["filtered", "failed", "pending"])
def test_only_summarized_articles_are_embedded(vectors, db_session, status):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, status=status, cleaned_content="x")
    assert _embed(db_session, article.id)["chunks"] == 0
    assert vectors.calls == []


def test_an_article_without_text_is_not_embedded(vectors, db_session):
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "T", "Özet", content="   ")
    assert _embed(db_session, article.id)["chunks"] == 0 and vectors.calls == []


def test_without_full_text_the_rss_text_is_embedded_as_plain_text(vectors, db_session):
    # Paywalled / robots.txt-blocked sources (WSJ, Independent Türkçe…) never get a scraped page,
    # but their RSS item often carries the whole story — the summary was written from it too.
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, title="Kriz", status="summarized", cleaned_content="",
                            raw_content="<p>Enerji <b>krizi</b> derinleşiyor&nbsp;ve fiyatlar artıyor.</p>")

    outcome = _embed(db_session, article.id)

    assert outcome["chunks"] == 1
    sent = vectors.calls[0][0]
    assert "Enerji krizi derinleşiyor ve fiyatlar artıyor." in sent and "<" not in sent


def test_a_page_scraped_later_replaces_the_rss_embedding(vectors, db_session):
    feed = _make_feed(db_session)
    article = _make_article(db_session, feed.id, title="T", status="summarized", raw_content="RSS metni")
    _embed(db_session, article.id)
    crud.update_article_content(db_session, article.id, cleaned_content="Tam sayfa metni")

    assert _embed(db_session, article.id)["chunks"] == 1
    texts = [r.text for r in db_session.query(models.ArticleChunkEmbedding).filter_by(article_id=article.id)]
    assert texts == ["Tam sayfa metni"]


def test_nothing_is_embedded_without_pgvector(vectors, db_session, monkeypatch):
    monkeypatch.setitem(database.vector_support, "available", False)
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "T", "Özet", content="Inhalt")
    assert _embed(db_session, article.id)["chunks"] == 0 and vectors.calls == []


def test_a_failing_embedding_never_fails_the_article(vectors, db_session):
    vectors.fail = True
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "T", "Özet", content="Inhalt")

    cost = asyncio.run(summary_service.embed_article_safely(db_session, article.id))

    assert cost == 0.0
    db_session.refresh(article)
    assert article.status == "summarized"
    log = db_session.query(models.ProcessingLog).filter_by(article_id=article.id, agent_name="embedder").one()
    assert log.status == "error"


def test_deleting_articles_deletes_their_embeddings(vectors, db_session):
    feed = _make_feed(db_session)
    one = _summarized(db_session, feed, "Bir", "Özet", content="Inhalt", priority="high")
    two = _summarized(db_session, feed, "İki", "Özet", content="Inhalt", priority="high")
    _embed(db_session, one.id)
    _embed(db_session, two.id)

    crud.delete_article(db_session, one.id)
    crud.delete_articles_by_priority(db_session, "high")

    assert db_session.query(models.ArticleChunkEmbedding).count() == 0


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------

def test_fuse_rankings_rewards_articles_found_by_both_methods():
    fused = tools.fuse_rankings({
        "chunk": [(1, 10, "chunk of 1", 0.1), (2, 20, "chunk of 2", 0.2), (2, 21, "another chunk of 2", 0.3)],
        "keyword": [(2, 21, "keyword chunk of 2", 5.0), (3, 30, "keyword chunk of 3", 1.0)],
    })
    assert [hit["article_id"] for hit in fused] == [2, 1, 3]
    assert fused[0]["matched_by"] == ["chunk", "keyword"]
    assert fused[0]["evidence"] == "chunk of 2"  # the best chunk by meaning
    assert fused[2]["evidence"] == "keyword chunk of 3"  # found by keyword only


@pytest.fixture()
def corpus(vectors, db_session):
    feed = _make_feed(db_session, title="DW")
    energy = _summarized(db_session, feed, "Energiepreise steigen", "Enerji fiyatları artıyor.",
                         content="Die Energiepreise steigen. Energie wird teurer.", priority="high")
    election = _summarized(db_session, feed, "Wahl in Sachsen", "Seçim sonuçları açıklandı.",
                           content="Die Wahl in Sachsen ist entschieden.", priority="med")
    war = _summarized(db_session, feed, "Krieg in der Ukraine", "Savaş sürüyor.",
                      content="Der Krieg geht weiter.", priority="low")
    for article in (energy, election, war):
        _embed(db_session, article.id)
    return {"energy": energy, "election": election, "war": war}


def test_semantic_search_finds_the_relevant_article_first(corpus, db_session):
    result = asyncio.run(tools.run_semantic_search_tool({"query": "enerji krizi"}, "a1"))

    assert result["ok"]
    hits = json.loads(result["content"])["results"]
    assert hits[0]["id"] == corpus["energy"].id
    assert hits[0]["feed"] == "DW" and hits[0]["priority"] == "high"
    assert "Energie" in hits[0]["evidence"]
    assert result["artifact"]["rows"][0][0] == corpus["energy"].id
    assert result["cost"] > 0


def test_semantic_search_applies_its_filters(corpus, db_session):
    result = asyncio.run(tools.run_semantic_search_tool({"query": "enerji", "priorities": ["med", "low"]}, "a1"))
    ids = [hit["id"] for hit in json.loads(result["content"])["results"]]
    assert corpus["energy"].id not in ids and ids


@pytest.mark.parametrize("asked", ["ABD-İran Krizi", "abd-iran krizi", "ABD-IRAN KRİZİ"])
def test_semantic_search_topic_filter_matches_turkish_dotted_capitals(corpus, db_session, asked):
    # Python lowers "İ" to "i" + U+0307, PostgreSQL to "i": every topic with an "İ" in its name
    # ("ABD-İran Krizi") matched nothing, so a topic-filtered search returned no results.
    topic = models.Topic(name="ABD-İran Krizi", description="x")
    db_session.add(topic)
    db_session.commit()
    db_session.add(models.ArticleTopic(article_id=corpus["war"].id, topic_id=topic.id, confidence=1.0))
    db_session.commit()

    result = asyncio.run(tools.run_semantic_search_tool({"query": "savaş", "topics": [asked]}, "a1"))
    ids = [hit["id"] for hit in json.loads(result["content"])["results"]]
    assert ids == [corpus["war"].id]


def test_semantic_search_rejects_a_bad_date(corpus):
    result = asyncio.run(tools.run_semantic_search_tool({"query": "x", "date_from_utc": "dün"}, "a1"))
    assert not result["ok"]


def test_semantic_search_is_offered_only_with_pgvector(monkeypatch, db_session):
    monkeypatch.setitem(database.vector_support, "available", False)
    monkeypatch.setitem(database.vector_support, "reason", "pgvector yok")
    assert "semantic_search" not in tools.get_enabled_chat_tools(db_session)
    assert tools.unavailable_reason("semantic_search") == "pgvector yok"
    monkeypatch.setitem(database.vector_support, "available", True)
    assert "semantic_search" in tools.get_enabled_chat_tools(db_session)


# ---------------------------------------------------------------------------
# Backfill + endpoints
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_backfill_status():
    from app.tasks import background
    background._embedding_status.update(status="idle", total=0, done=0, failed=0, cost=0.0, error=None)


def test_backfill_embeds_the_missing_articles(vectors, db_session):
    from app.tasks import background
    feed = _make_feed(db_session)
    done = _summarized(db_session, feed, "Hazır", "Özet", content="x")
    _embed(db_session, done.id)
    missing = [_summarized(db_session, feed, f"Eksik {i}", "Özet", content="y") for i in range(2)]
    _make_article(db_session, feed.id, status="filtered", cleaned_content="z")  # not summarized
    rss_only = _make_article(db_session, feed.id, title="RSS", status="summarized", raw_content="RSS metni")
    _summarized(db_session, feed, "Metinsiz", "Özet", content="")  # nothing to embed

    assert background.register_embedding_backfill()
    asyncio.run(background.embed_missing_articles_task())

    status = background.get_embedding_backfill_status()
    assert (status["status"], status["total"], status["done"], status["failed"]) == ("done", 3, 3, 0)
    embedded = {r.article_id for r in db_session.query(models.ArticleChunkEmbedding)}
    assert embedded == {done.id, rss_only.id, *(a.id for a in missing)}


def test_embedding_status_endpoint(client, auth_headers, vectors, db_session):
    feed = _make_feed(db_session)
    article = _summarized(db_session, feed, "T", "Özet", content="Inhalt")
    _summarized(db_session, feed, "U", "Özet", content="Inhalt")
    _embed(db_session, article.id)
    _make_article(db_session, feed.id, title="RSS", status="summarized", raw_content="RSS metni")
    _summarized(db_session, feed, "Metinsiz", "Özet", content="")

    body = client.get("/api/chat/embeddings/status", headers=auth_headers).json()

    assert body["available"] is True
    # The UI's "eksik" = summarized - embedded - no_text: only what a backfill can actually embed.
    assert (body["summarized"], body["embedded"], body["no_text"]) == (4, 1, 1) and body["chunks"] >= 1
    assert body["model"] == "text-embedding-3-large" and body["dimensions"] == 1536
    assert body["job"]["status"] == "idle"


def test_backfill_endpoint_runs_the_job(client, admin_headers, vectors, db_session):
    feed = _make_feed(db_session)
    _summarized(db_session, feed, "T", "Özet", content="Inhalt")

    response = client.post("/api/chat/embeddings/backfill", headers=admin_headers)

    assert response.status_code == 200
    # TestClient runs background tasks before returning; the job has finished.
    body = client.get("/api/chat/embeddings/status", headers=admin_headers).json()
    assert body["embedded"] == 1 and body["job"]["status"] == "done"


def test_backfill_endpoint_refuses_without_pgvector_or_while_running(client, admin_headers, monkeypatch):
    from app.tasks import background
    monkeypatch.setitem(database.vector_support, "available", False)
    monkeypatch.setitem(database.vector_support, "reason", "pgvector yok")
    assert client.post("/api/chat/embeddings/backfill", headers=admin_headers).status_code == 409

    monkeypatch.setitem(database.vector_support, "available", True)
    background._embedding_status["status"] = "running"
    assert client.post("/api/chat/embeddings/backfill", headers=admin_headers).status_code == 409


def test_embedding_endpoints_require_auth(client):
    assert client.get("/api/chat/embeddings/status").status_code == 401
    assert client.post("/api/chat/embeddings/backfill").status_code == 401
