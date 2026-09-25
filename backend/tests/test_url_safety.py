"""
Regression (#33): the SSRF guard only ran when a feed was saved. Fetches now re-check the host at
fetch time (DNS may have changed since), article URLs from inside a feed are checked too, and
every redirect hop is validated instead of being followed blindly.

DNS is faked by the autouse `fake_dns` fixture in conftest: hosts ending in ".internal" resolve
to a private address, everything else to a public one.
"""
import asyncio
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from app.agents import tools
from app.core import url_safety
from app.core.exceptions import RSSFetchError


@pytest.mark.parametrize("url, safe", [
    ("https://rss.dw.com/feed", True),
    ("http://feed.internal/rss", False),
    ("http://127.0.0.1/admin", False),
    ("http://169.254.169.254/latest/meta-data", False),
    ("file:///etc/passwd", False),
    ("ftp://rss.dw.com/feed", False),
])
def test_is_public_url(url, safe):
    assert url_safety.is_public_url(url) is safe


def test_feed_fetch_rechecks_the_host_at_fetch_time():
    with patch("app.agents.tools.feedparser.parse") as parse:
        with pytest.raises(RSSFetchError):
            asyncio.run(tools.fetch_rss_feed("http://feed.internal/rss"))
    parse.assert_not_called()


def test_feed_redirect_to_a_private_host_is_refused():
    handler = tools._PublicOnlyRedirectHandler()
    request = urllib.request.Request("https://rss.dw.com/feed")

    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://169.254.169.254/latest")

    assert handler.redirect_request(request, None, 302, "Found", {}, "https://cdn.dw.com/feed") is not None


class _FakeResponse:
    def __init__(self, status, headers=None, body=""):
        self.status, self.headers, self._body = status, headers or {}, body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def text(self):
        return self._body


class _FakeSession:
    """aiohttp.ClientSession stand-in: serves `pages[url]` and records every requested URL."""

    def __init__(self, pages, requested):
        self._pages, self._requested = pages, requested

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        assert kwargs.get("allow_redirects") is False, "redirects must be followed hop by hop"
        self._requested.append(url)
        return self._pages[url]


@pytest.fixture
def scraper(monkeypatch):
    monkeypatch.setattr(tools.settings, "scraping_delay", 0)
    monkeypatch.setattr(tools.settings, "scraping_enabled", True)

    async def allowed(url):
        return True

    monkeypatch.setattr(tools, "check_robots_txt", allowed)
    requested = []

    def install(pages):
        monkeypatch.setattr(tools.aiohttp, "ClientSession", lambda *a, **k: _FakeSession(pages, requested))

    return install, requested


def test_article_url_on_a_private_host_is_not_fetched(scraper):
    install, requested = scraper
    install({})

    assert asyncio.run(tools.extract_article_content("http://10.1.2.3/secret")) == (None, None, None)
    assert requested == []


def test_article_redirect_to_a_private_host_is_not_followed(scraper):
    install, requested = scraper
    install({"https://news.example/a": _FakeResponse(302, {"Location": "http://metadata.internal/token"})})

    assert asyncio.run(tools.extract_article_content("https://news.example/a")) == (None, None, None)
    assert requested == ["https://news.example/a"]


def test_article_redirect_to_a_public_host_is_followed(scraper):
    install, requested = scraper
    html = "<html><body><article><p>" + "Haber metni. " * 60 + "</p></article></body></html>"
    install({
        "https://news.example/a": _FakeResponse(301, {"Location": "/b"}),
        "https://news.example/b": _FakeResponse(200, body=html),
    })

    content, _, _ = asyncio.run(tools.extract_article_content("https://news.example/a"))

    assert requested == ["https://news.example/a", "https://news.example/b"]
    assert content and "Haber metni." in content
