"""
Tests for app/agents/tools.py — the pure helpers, plus the feed/robots.txt fetches against a local
HTTP server (never the real network).
"""
import asyncio
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.agents import tools
from app.agents.tools import _extract_image_url


def test_extract_image_url_prefers_media_content_marked_as_image():
    entry = {
        "media_content": [{"url": "https://static.dw.com/hero.jpg", "medium": "image"}],
        "media_thumbnail": [{"url": "https://static.dw.com/thumb.jpg"}],
    }
    assert _extract_image_url(entry) == "https://static.dw.com/hero.jpg"


def test_extract_image_url_falls_back_to_media_thumbnail():
    entry = {"media_thumbnail": [{"url": "https://static.dw.com/thumb.jpg"}]}
    assert _extract_image_url(entry) == "https://static.dw.com/thumb.jpg"


def test_extract_image_url_falls_back_to_image_enclosure():
    entry = {
        "enclosures": [
            {"href": "https://static.dw.com/audio.mp3", "type": "audio/mpeg"},
            {"href": "https://static.dw.com/photo.jpg", "type": "image/jpeg"},
        ]
    }
    assert _extract_image_url(entry) == "https://static.dw.com/photo.jpg"


def test_extract_image_url_recognizes_image_extension_without_medium_or_type():
    entry = {"media_content": [{"url": "https://static.dw.com/hero.png"}]}
    assert _extract_image_url(entry) == "https://static.dw.com/hero.png"


def test_extract_image_url_returns_none_when_nothing_image_like():
    entry = {"enclosures": [{"href": "https://static.dw.com/audio.mp3", "type": "audio/mpeg"}]}
    assert _extract_image_url(entry) is None


def test_extract_image_url_returns_none_for_empty_entry():
    assert _extract_image_url({}) is None


# ==================== Bot-protected sources (feed + robots.txt fetches) ====================
# Cloudflare/Akamai-style protection answers 403 to library default User-Agents. Le Figaro 403'd
# feedparser's own UA, so the feed could not be added; Foreign Policy, Kisa Dalga, Politico EU, NZZ
# 403'd urllib's "Python-urllib" UA on robots.txt, which was read as "disallow all" — so their pages
# were never scraped and only the RSS teaser got summarized.

_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>
<item><title>Haber</title><link>https://example.com/a</link></item></channel></rss>"""


@contextmanager
def _site(routes, allowed_ua=None):
    """Local site serving `routes` ({path: (status, body)}); with `allowed_ua`, every request whose
    User-Agent doesn't start with it gets a 403, like a bot-protected news site."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            ua = self.headers.get("User-Agent", "")
            seen.append((self.path, ua))
            status, body = routes.get(self.path, (404, b"not found"))
            if allowed_ua and not ua.startswith(allowed_ua):
                status, body = 403, b"blocked"
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", seen
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def local_fetch(monkeypatch):
    monkeypatch.setattr(tools, "assert_public_url", lambda url: None)
    monkeypatch.setattr(tools, "_ROBOTS_CACHE", {})  # each test's server starts unknown


def test_feed_fetch_identifies_as_the_app_so_bot_protected_feeds_can_be_added(local_fetch):
    with _site({"/rss": (200, _RSS)}, allowed_ua="NewsSummarizer/") as (base, seen):
        asyncio.run(tools.test_feed_connection(f"{base}/rss"))  # raised "HTTP 403" before

    assert all(ua.startswith("NewsSummarizer/") for _, ua in seen)


def test_robots_txt_is_fetched_with_the_app_user_agent(local_fetch):
    robots = b"User-agent: *\nDisallow: /private/\n"
    with _site({"/robots.txt": (200, robots)}, allowed_ua="NewsSummarizer/") as (base, seen):
        allowed = asyncio.run(tools.check_robots_txt(f"{base}/news/a"))

    assert allowed is True
    assert seen and seen[0][1].startswith("NewsSummarizer/")


@pytest.mark.parametrize("status", [401, 403, 404])
def test_unreadable_robots_txt_does_not_block_scraping(local_fetch, status):
    # RFC 9309 §2.3.1.3: a 4xx robots.txt is "unavailable" and the crawler may access the site.
    # A WAF answering 403 to the robots.txt request says nothing about the site's crawl rules.
    with _site({"/robots.txt": (status, b"")}) as (base, _):
        assert asyncio.run(tools.check_robots_txt(f"{base}/news/a")) is True


def test_robots_txt_disallow_is_still_respected(local_fetch):
    robots = b"User-agent: *\nDisallow: /\n"
    with _site({"/robots.txt": (200, robots)}) as (base, _):
        assert asyncio.run(tools.check_robots_txt(f"{base}/news/a")) is False


# ==================== Full text without scraping the page ====================
# Politico's feed carries the whole article in <content:encoded>, while its pages 403 every
# non-browser client; Medyascope (WordPress) 403s its pages but serves the same post through the
# public WordPress REST API. Both used to end with the 100-200 char RSS teaser being summarized.

_LONG_HTML = "".join(f"<p>Paragraf {i}: " + "uzun haber metni " * 8 + "</p>" for i in range(12))


class _Entry(dict):
    """feedparser entry stand-in (dict access + attribute access for `published`)."""
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e


class _Feed:
    def __init__(self, entries):
        self.entries, self.bozo = entries, False


def _parse_entries(monkeypatch, entries):
    monkeypatch.setattr(tools, "assert_public_url", lambda url: None)
    monkeypatch.setattr(tools.feedparser, "parse", lambda *a, **k: _Feed(entries))
    return asyncio.run(tools.fetch_rss_feed("https://example.com/rss"))


def test_feed_keeps_the_longer_content_encoded_as_raw_content(monkeypatch):
    [article] = _parse_entries(monkeypatch, [_Entry(
        link="https://example.com/a", title="T", description="Kısa özet",
        content=[{"value": _LONG_HTML}],
    )])

    # Stored as is: parsed only if the page fetch of an important article comes up short.
    assert article["raw_content"] == _LONG_HTML


def test_feed_keeps_the_description_when_content_encoded_is_shorter(monkeypatch):
    [article] = _parse_entries(monkeypatch, [_Entry(
        link="https://example.com/a", title="T", description="Biraz daha uzun açıklama metni",
        content=[{"value": "<p>Kısa</p>"}],
    )])

    assert article["raw_content"] == "Biraz daha uzun açıklama metni"


def test_feed_fetch_does_not_parse_entry_html(monkeypatch):
    # Every refresh lists mostly known entries; parsing their HTML on the event loop was wasted work.
    def no_parse(*a, **k):
        raise AssertionError("feed entries must not be parsed at fetch time")

    monkeypatch.setattr(tools, "html_to_text", no_parse)
    _parse_entries(monkeypatch, [_Entry(link="https://example.com/a", title="T", description="d",
                                        content=[{"value": _LONG_HTML}])])


@pytest.mark.parametrize("html, text", [
    # Line breaks inside the source HTML are not paragraphs.
    ("<p>The minister said\nthat talks <a>would\n resume</a> today.</p>",
     "The minister said that talks would resume today."),
    # Text right before a block tag stays its own paragraph.
    ("Lead sentence<p>Para one</p>", "Lead sentence\nPara one"),
    ("<p>a<br>b</p><ul><li>c</li><li>d</li></ul>", "a\nb\nc\nd"),
    # Entities are decoded exactly once.
    ("<p>Use &amp;lt;b&amp;gt; tags &amp;not here</p>", "Use &lt;b&gt; tags &not here"),
    # Markup that is not text: scripts, comments, WordPress' feed footer.
    ("<p>Body</p><script>x()</script><!-- note --><p>The post Haber appeared first on Medyascope.</p>",
     "Body"),
])
def test_html_to_text(html, text):
    assert tools.html_to_text(html) == text


class _Resp:
    def __init__(self, status, body="", location=None):
        self.status, self._body = status, body
        self.headers = {"Location": location} if location else {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._body


class _Session:
    def __init__(self, routes, requested):
        self._routes, self._requested = routes, requested

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, params=None, **kwargs):
        if params:
            url = f"{url}?" + "&".join(f"{k}={v}" for k, v in params.items())
        self._requested.append(url)
        return self._routes.get(url, _Resp(404, "not found"))


@pytest.fixture
def fake_web(monkeypatch):
    monkeypatch.setattr(tools.settings, "scraping_delay", 0)
    monkeypatch.setattr(tools.settings, "scraping_enabled", True)

    async def allowed(url):
        return True

    monkeypatch.setattr(tools, "check_robots_txt", allowed)
    web = SimpleNamespace(routes={}, requested=[])
    monkeypatch.setattr(tools.aiohttp, "ClientSession",
                        lambda *a, **k: _Session(web.routes, web.requested))
    return web


_WP_URL = "https://medyascope.tv/2026/11/10/ukraynada-savasin-bedeli/"
_WP_API = "https://medyascope.tv/wp-json/wp/v2/posts?slug=ukraynada-savasin-bedeli&_fields=content"


def test_blocked_wordpress_page_is_read_from_the_rest_api(fake_web):
    fake_web.routes.update({
        _WP_URL: _Resp(403, "Just a moment..."),
        _WP_API: _Resp(200, json.dumps([{"content": {"rendered": _LONG_HTML}}])),
    })

    content, *_ = asyncio.run(tools.extract_article_content(_WP_URL))

    assert content and content.startswith("Paragraf 0: uzun haber metni")
    assert len(content.split("\n")) == 12


@pytest.mark.parametrize("api", [
    _Resp(404, "not found"),  # not a WordPress site
    _Resp(200, "[]"),  # no post with that slug
    _Resp(200, "<html>challenge</html>"),  # API blocked too
])
def test_blocked_page_without_a_usable_wordpress_api_still_yields_nothing(fake_web, api):
    fake_web.routes.update({_WP_URL: _Resp(403, "blocked"), _WP_API: api})

    # The source refused us: reported as blocked (the free-source search may run).
    assert asyncio.run(tools.extract_article_content(_WP_URL)) == (None, None, None, False, True)


@pytest.mark.parametrize("status", [404, 429, 503])
def test_wordpress_api_is_not_tried_unless_the_page_was_refused(fake_web, status):
    # 404 = no such page; 429/503 = slow down / temporarily down — two more requests would only
    # add load to a host that just asked for less.
    fake_web.routes[_WP_URL] = _Resp(status, "nope")

    assert asyncio.run(tools.extract_article_content(_WP_URL)) == (None, None, None, False, False)
    assert fake_web.requested == [_WP_URL]


def test_wordpress_api_redirect_is_followed(fake_web):
    www_api = _WP_API.replace("://medyascope.tv", "://www.medyascope.tv")
    fake_web.routes.update({
        _WP_URL: _Resp(403, "blocked"),
        _WP_API: _Resp(301, location=www_api),
        www_api: _Resp(200, json.dumps([{"content": {"rendered": _LONG_HTML}}])),
    })

    content, *_ = asyncio.run(tools.extract_article_content(_WP_URL))

    assert content and content.startswith("Paragraf 0")


def test_wordpress_slug_comes_from_the_page_that_refused(fake_web):
    short = "https://medyascope.tv/?p=123"
    fake_web.routes.update({
        short: _Resp(301, location=_WP_URL),
        _WP_URL: _Resp(403, "blocked"),
        _WP_API: _Resp(200, json.dumps([{"content": {"rendered": _LONG_HTML}}])),
    })

    content, *_ = asyncio.run(tools.extract_article_content(short))

    assert content and content.startswith("Paragraf 0")


def test_robots_txt_is_fetched_once_per_host(local_fetch):
    # The page check and the WordPress API check (and every other article of the same site) share
    # one robots.txt fetch instead of asking the host again seconds later.
    with _site({"/robots.txt": (200, b"User-agent: *\nDisallow: /private/\n")}) as (base, seen):
        first = asyncio.run(tools.check_robots_txt(f"{base}/news/a"))
        api = asyncio.run(tools.check_robots_txt(f"{base}/wp-json/wp/v2/posts"))
        private = asyncio.run(tools.check_robots_txt(f"{base}/private/x"))

    assert (first, api, private) == (True, True, False)
    assert [path for path, _ in seen] == ["/robots.txt"]


@pytest.mark.parametrize("html, expected", [
    ('<script type="application/ld+json">{"isAccessibleForFree": false}</script>', True),
    ('<script type="application/ld+json">{"isAccessibleForFree":"False"}</script>', True),
    ('<script type="application/ld+json">{"isAccessibleForFree": "true"}</script>', False),
    ("<html><p>no structured data</p></html>", False),
    ("", False),
])
def test_is_paywalled_reads_the_schema_org_flag(html, expected):
    assert tools.is_paywalled(html) is expected


def _ld(*objects):
    return "".join(f'<script type="application/ld+json">{json.dumps(o)}</script>' for o in objects)


@pytest.mark.parametrize("html, expected", [
    # A free article that embeds a related premium piece (hasPart / related) is not paywalled.
    (_ld({"@type": "NewsArticle", "isAccessibleForFree": True,
          "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": False}}), False),
    (_ld({"@type": "NewsArticle", "headline": "Frei",
          "relatedLink": [{"@type": "NewsArticle", "isAccessibleForFree": False}]}), False),
    # A teaser object for another article next to the page's own (free) article.
    (_ld({"@type": "NewsArticle", "headline": "Frei", "isAccessibleForFree": "true"},
         {"@type": "NewsArticle", "headline": "Premium-Teaser", "isAccessibleForFree": False}), False),
    (_ld({"@graph": [{"@type": "WebSite"},
                     {"@type": "NewsArticle", "headline": "Frei", "isAccessibleForFree": True},
                     {"@type": "NewsArticle", "headline": "Teaser", "isAccessibleForFree": False}]}), False),
    # The page's own article marked paywalled — directly, inside @graph, or in a list.
    (_ld({"@graph": [{"@type": "WebSite"},
                     {"@type": "NewsArticle", "isAccessibleForFree": False,
                      "hasPart": {"@type": "WebPageElement", "isAccessibleForFree": False}}]}), True),
    (_ld([{"@type": ["NewsArticle", "ReportageNewsArticle"], "isAccessibleForFree": "False"}]), True),
])
def test_is_paywalled_only_reads_the_pages_own_article(html, expected):
    """Regression (review): any `"isAccessibleForFree": false` anywhere in the HTML (a related
    premium piece, a hasPart block) marked a short free article as a crawl failure."""
    assert tools.is_paywalled(html) is expected


def test_a_page_that_refuses_us_is_reported_as_blocked(fake_web):
    url = "https://blocked.example/haber"
    fake_web.routes[url] = _Resp(403, "blocked")

    *_, paywalled, blocked = asyncio.run(tools.extract_article_content(url))

    assert (paywalled, blocked) == (False, True)


@pytest.mark.parametrize("status", [404, 500, 503])
def test_a_missing_or_failing_page_is_not_reported_as_blocked(fake_web, status):
    url = "https://down.example/haber"
    fake_web.routes[url] = _Resp(status, "error")

    content, *_, blocked = asyncio.run(tools.extract_article_content(url))

    assert content is None and blocked is False


def test_disabled_scraping_is_not_reported_as_blocked(monkeypatch):
    monkeypatch.setattr(tools.settings, "scraping_enabled", False)

    *_, blocked = asyncio.run(tools.extract_article_content("https://dw.example/haber"))

    assert blocked is False


def test_paywalled_page_is_reported_with_its_lead(fake_web):
    url = "https://www.spiegel.de/politik/kommentar-a.html"
    page = ('<html><head><script type="application/ld+json">{"@type":"NewsArticle",'
            '"isAccessibleForFree":false}</script></head><body><article>'
            + "".join(f"<p>Satz {i} des Vorspanns mit genug Text für trafilatura.</p>" for i in range(5))
            + "</article></body></html>")
    fake_web.routes[url] = _Resp(200, page)

    content, _, _, paywalled, _ = asyncio.run(tools.extract_article_content(url))

    assert paywalled is True
    assert content
