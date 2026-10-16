"""
Tests for GET /api/stats/analysis (Analiz tab severity analytics, app/api/routes/summaries.py).
"""
from datetime import datetime, timezone, timedelta

import pytest

from tests.conftest import _make_feed, _make_article, _make_topic, _make_article_topic


def _today_noon():
    return datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)


def _labelled(db_session, feed_id, priority, published_at, **kwargs):
    return _make_article(
        db_session, feed_id, priority=priority, status="summarized", published_at=published_at, **kwargs
    )


def test_analysis_stats_requires_auth(client):
    response = client.get("/api/stats/analysis")
    assert response.status_code == 401


@pytest.mark.parametrize("days", [0, 9, 365])
def test_analysis_stats_rejects_unsupported_range(client, auth_headers, days):
    response = client.get("/api/stats/analysis", params={"days": days}, headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.parametrize("days", [7, 30, 90])
def test_analysis_stats_zero_fills_every_day_of_the_range(client, auth_headers, days):
    response = client.get("/api/stats/analysis", params={"days": days}, headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == days
    assert len(body["trend"]) == days
    assert body["trend"][-1]["date"] == _today_noon().date().isoformat()
    assert all(d["total"] == 0 for d in body["trend"])
    assert body["totals"] == {
        "high": 0, "med": 0, "low": 0, "total": 0, "high_ratio": 0.0, "prev_high_ratio": None,
    }
    assert body["topics"] == []
    assert body["feeds"] == []


def test_analysis_stats_defaults_to_30_days(client, auth_headers):
    body = client.get("/api/stats/analysis", headers=auth_headers).json()
    assert body["days"] == 30
    assert len(body["trend"]) == 30


def test_analysis_stats_trend_buckets_by_day_and_priority(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    today = _today_noon()
    yesterday = today - timedelta(days=1)
    _labelled(db_session, feed.id, "high", today)
    _labelled(db_session, feed.id, "high", today)
    _labelled(db_session, feed.id, "low", today)
    _labelled(db_session, feed.id, "med", yesterday)

    body = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()

    assert body["trend"][-1] == {
        "date": today.date().isoformat(), "high": 2, "med": 0, "low": 1, "total": 3,
    }
    assert body["trend"][-2] == {
        "date": yesterday.date().isoformat(), "high": 0, "med": 1, "low": 0, "total": 1,
    }
    totals = body["totals"]
    assert (totals["high"], totals["med"], totals["low"], totals["total"]) == (2, 1, 1, 4)
    assert totals["high_ratio"] == pytest.approx(0.5)


def test_analysis_stats_excludes_unlabelled_error_and_out_of_range(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, "Savaş")
    today = _today_noon()
    articles = [
        _labelled(db_session, feed.id, "high", today),
        _make_article(db_session, feed.id, priority=None, status="summarized", published_at=today),
        _make_article(db_session, feed.id, priority="high", status="failed", published_at=today),
        _labelled(db_session, feed.id, "high", today - timedelta(days=7)),  # just outside 7-day range
        _labelled(db_session, feed.id, "high", today + timedelta(days=2)),  # future-dated
    ]
    # The topic breakdown runs its own query — it must apply the same filters.
    for article in articles:
        _make_article_topic(db_session, article.id, topic.id)

    body = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()

    assert body["totals"]["total"] == 1
    assert sum(d["total"] for d in body["trend"]) == 1
    assert sum(f["total"] for f in body["feeds"]) == 1
    assert [(t["name"], t["high"], t["total"]) for t in body["topics"]] == [("Savaş", 1, 1)]


def test_analysis_stats_excludes_unimportant_articles_with_a_stray_priority(client, auth_headers, db_session):
    """The classifier can answer {"importance": "unimportant", "priority": "low"} and the pipeline
    stores that priority as-is — but an Önemsiz (filtered) article has no severity and must not
    count as high/med/low anywhere: not in the totals, the trend, topics, feeds or the previous period."""
    feed = _make_feed(db_session)
    topic = _make_topic(db_session, "Spor")
    today = _today_noon()
    _make_article(db_session, feed.id, priority="high", importance="important", status="summarized",
                  published_at=today)
    stray = _make_article(db_session, feed.id, priority="low", importance="unimportant", status="filtered",
                          published_at=today)
    _make_article_topic(db_session, stray.id, topic.id)
    # Previous 7-day period holds only articles without a real severity -> nothing to compare with.
    _make_article(db_session, feed.id, priority="high", importance="unimportant", status="filtered",
                  published_at=today - timedelta(days=10))
    _make_article(db_session, feed.id, priority="high", status="failed", published_at=today - timedelta(days=10))

    body = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()

    totals = body["totals"]
    assert (totals["high"], totals["med"], totals["low"], totals["total"]) == (1, 0, 0, 1)
    assert totals["high_ratio"] == pytest.approx(1.0)
    assert totals["prev_high_ratio"] is None
    assert body["trend"][-1]["low"] == 0
    assert body["topics"] == []
    assert [f["total"] for f in body["feeds"]] == [1]


def test_analysis_stats_counts_read_articles_too(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    today = _today_noon()
    _labelled(db_session, feed.id, "high", today, is_read=True)
    _labelled(db_session, feed.id, "low", today)

    totals = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()["totals"]

    assert (totals["high"], totals["low"], totals["total"]) == (1, 1, 2)


def test_analysis_stats_range_and_previous_period_boundaries(client, auth_headers, db_session):
    """7-day range = [today-6d 00:00, tomorrow 00:00); previous period = the 7 days before it."""
    feed = _make_feed(db_session)
    midnight = _today_noon().replace(hour=0)
    range_start = midnight - timedelta(days=6)
    prev_start = range_start - timedelta(days=7)
    second = timedelta(seconds=1)
    _labelled(db_session, feed.id, "high", range_start)           # first instant of the range
    _labelled(db_session, feed.id, "low", range_start - second)   # last instant of the previous period
    _labelled(db_session, feed.id, "high", prev_start)            # first instant of the previous period
    _labelled(db_session, feed.id, "high", prev_start - second)   # before both periods -> ignored

    body = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()

    assert body["trend"][0] == {
        "date": range_start.date().isoformat(), "high": 1, "med": 0, "low": 0, "total": 1,
    }
    assert body["totals"]["total"] == 1
    assert body["totals"]["high_ratio"] == pytest.approx(1.0)
    assert body["totals"]["prev_high_ratio"] == pytest.approx(0.5)


def test_analysis_stats_falls_back_to_fetched_at(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    yesterday = _today_noon() - timedelta(days=1)
    article = _labelled(db_session, feed.id, "med", None)
    article.fetched_at = yesterday
    db_session.commit()

    body = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()

    assert body["trend"][-2]["date"] == yesterday.date().isoformat()
    assert body["trend"][-2]["med"] == 1


def test_analysis_stats_compares_high_ratio_with_previous_period(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    today = _today_noon()
    _labelled(db_session, feed.id, "high", today)
    _labelled(db_session, feed.id, "low", today)
    # Previous 7-day period: 1 high out of 4
    for priority in ("high", "low", "low", "low"):
        _labelled(db_session, feed.id, priority, today - timedelta(days=10))

    totals = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()["totals"]

    assert totals["high_ratio"] == pytest.approx(0.5)
    assert totals["prev_high_ratio"] == pytest.approx(0.25)


def test_analysis_stats_topic_breakdown_sorted_by_high_then_total(client, auth_headers, db_session):
    feed = _make_feed(db_session)
    today = _today_noon()
    war = _make_topic(db_session, "Savaş", color="#ff0000")
    sport = _make_topic(db_session, "Spor")
    _make_topic(db_session, "Boş Konu")  # no articles -> not listed

    for priority in ("high", "low"):
        _make_article_topic(db_session, _labelled(db_session, feed.id, priority, today).id, war.id)
    for priority in ("med", "low", "low"):
        _make_article_topic(db_session, _labelled(db_session, feed.id, priority, today).id, sport.id)

    topics = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()["topics"]

    assert [t["name"] for t in topics] == ["Savaş", "Spor"]
    assert topics[0] == {
        "topic_id": war.id, "name": "Savaş", "color": "#ff0000", "high": 1, "med": 0, "low": 1, "total": 2,
    }
    assert (topics[1]["med"], topics[1]["low"], topics[1]["total"]) == (1, 2, 3)


def test_analysis_stats_feed_profile(client, auth_headers, db_session):
    today = _today_noon()
    big = _make_feed(db_session, "https://example.com/big", title="Big")
    small = _make_feed(db_session, "https://example.com/small", title="Small")
    for priority in ("high", "low", "low", "low"):
        _labelled(db_session, big.id, priority, today)
    _labelled(db_session, small.id, "high", today)

    feeds = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()["feeds"]

    assert [f["title"] for f in feeds] == ["Big", "Small"]
    assert feeds[0]["total"] == 4
    assert feeds[0]["high_ratio"] == pytest.approx(0.25)
    assert feeds[1]["high_ratio"] == pytest.approx(1.0)


def test_analysis_stats_feed_without_title_is_named_by_its_url(client, auth_headers, db_session):
    feed = _make_feed(db_session, "https://example.com/untitled", title=None)
    _labelled(db_session, feed.id, "med", _today_noon())

    feeds = client.get("/api/stats/analysis", params={"days": 7}, headers=auth_headers).json()["feeds"]

    assert [(f["feed_id"], f["title"]) for f in feeds] == [(feed.id, "https://example.com/untitled")]
