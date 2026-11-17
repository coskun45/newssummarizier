"""
Tools for the news processing agents.
"""
import asyncio
import json
import feedparser
import trafilatura
from trafilatura.metadata import extract_metadata
import aiohttp
import logging
import urllib.error
import urllib.request
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from html import unescape
from datetime import timezone
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlencode, urljoin, urlparse
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup, Comment
from dateutil import parser as date_parser
from app.core.config import settings
from app.core.exceptions import RSSFetchError, ScrapingError
from app.core.url_safety import assert_public_url, is_public_url

logger = logging.getLogger(__name__)

# Feed and robots.txt fetches are blocking network I/O, so they run in a worker thread. Each socket
# operation has a real timeout (the handlers below): `asyncio.wait_for` only stops waiting, the
# thread would stay blocked. They get their own pool because asyncio's shared one also runs every
# other `to_thread` and the Asistan's synchronous LangGraph routers: fetches hung on a dead server
# filled it and locked up feed refresh, mails and the Asistan until a restart.
NETWORK_CALL_TIMEOUT_SECONDS = 30
_NETWORK_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="remote-fetch")
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)

# One identity for every request we make (feed, robots.txt, article page). Bot protection on news
# sites 403s library defaults ("feedparser/…", "Python-urllib/…"): Le Figaro's feed could not be
# added, and robots.txt 403s blocked Foreign Policy, Kisa Dalga, Politico EU and NZZ from scraping.
ROBOTS_USER_AGENT = "NewsSummarizer/1.0"
USER_AGENT = f"{ROBOTS_USER_AGENT} (+https://github.com/yourusername/news-summary)"

# The feed's own text (raw_content, e.g. Politico's whole article in <content:encoded>) replaces a
# missing or shorter page text only from this length on: NYT and Spiegel ship just a 100-250 char
# teaser there, which must not be stored as the article text (see summary_service.page_or_feed_text).
FEED_FULL_TEXT_MIN_CHARS = 1000
# Page answers that mean "you may not" rather than "no such page" (404) or "slow down / down for
# now" (429/503, where more requests would only add load): only these try the WordPress REST API.
_BLOCKED_STATUSES = (401, 403)
# robots.txt per host, reused by every article (and the WordPress API check) of that site.
_ROBOTS_CACHE: Dict[str, Tuple[float, RobotFileParser]] = {}
ROBOTS_CACHE_SECONDS = 600


class _TimeoutHTTPHandler(urllib.request.HTTPHandler):
    """Gives feedparser's connections a socket timeout; its parse() has no timeout argument."""

    def http_open(self, req):
        req.timeout = NETWORK_CALL_TIMEOUT_SECONDS
        return super().http_open(req)


class _TimeoutHTTPSHandler(urllib.request.HTTPSHandler):
    """The same for https feeds."""

    def https_open(self, req):
        req.timeout = NETWORK_CALL_TIMEOUT_SECONDS
        return super().https_open(req)


async def _run_remote_fetch(func, *args, **kwargs):
    """Run a blocking fetch on the dedicated pool, waiting at most the network timeout."""
    loop = asyncio.get_running_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(_NETWORK_POOL, partial(func, *args, **kwargs)),
        timeout=NETWORK_CALL_TIMEOUT_SECONDS,
    )


class _PublicOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """urllib redirect handler (feedparser, robots.txt) that refuses to follow a redirect to a
    non-public host — a public feed URL must not be able to bounce the backend into the internal
    network."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_url(newurl):
            raise urllib.error.URLError(f"Refusing redirect to a non-public address: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _extract_author(entry) -> Optional[str]:
    """Pull an author name from a feed entry, checking the common variants
    (plain author, Atom <author><name>, multiple authors, dc:creator)."""
    # Standard <author> / dc:creator (feedparser maps both to 'author')
    author = entry.get("author")
    if author and str(author).strip():
        return str(author).strip()

    # Atom <author><name> or several authors → list of dicts with 'name'
    authors = entry.get("authors")
    if authors:
        names = [
            a.get("name").strip()
            for a in authors
            if isinstance(a, dict) and a.get("name") and a.get("name").strip()
        ]
        if names:
            return ", ".join(names)

    # author_detail = {"name": ...}
    detail = entry.get("author_detail")
    if isinstance(detail, dict) and detail.get("name") and detail.get("name").strip():
        return detail["name"].strip()

    # Namespaced fallbacks just in case feedparser didn't normalise them
    for key in ("dc_creator", "creator"):
        val = entry.get(key)
        if val and str(val).strip():
            return str(val).strip()

    return None


_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")


def _looks_like_image_url(url: str) -> bool:
    return url.lower().split("?")[0].endswith(_IMAGE_EXTENSIONS)


def _extract_image_url(entry) -> Optional[str]:
    """Pull a representative image URL from a feed entry. DW and most news
    feeds expose one via the Media RSS extension (media:content/media:thumbnail)
    or a plain <enclosure> - checked in that order of preference."""
    media_content = entry.get("media_content")
    if media_content:
        for item in media_content:
            url = item.get("url")
            if url and (item.get("medium") == "image" or _looks_like_image_url(url)):
                return url

    media_thumbnail = entry.get("media_thumbnail")
    if media_thumbnail:
        url = media_thumbnail[0].get("url")
        if url:
            return url

    enclosures = entry.get("enclosures")
    if enclosures:
        for item in enclosures:
            url = item.get("href") or item.get("url")
            item_type = item.get("type", "") or ""
            if url and (item_type.startswith("image/") or _looks_like_image_url(url)):
                return url

    return None


def _entry_text(entry) -> str:
    """The entry's own text, as shipped: <content:encoded> (feedparser: `entry.content`) when it is
    longer than the <description> — Politico, Fox News and WordPress feeds put the whole article
    there. Not parsed here: every refresh lists mostly known entries, and only an important
    article whose page fetch comes up short ever needs it as text."""
    description = entry.get("description", "") or entry.get("summary", "") or ""
    blocks = [b.get("value") or "" for b in (entry.get("content") or []) if isinstance(b, dict)]
    longest = max(blocks, key=len, default="")
    return longest if len(longest) > len(description) else description


async def _fetch_and_parse(feed_url: str):
    """
    Fetch and parse a feed URL with feedparser, off the event loop and bounded by a timeout.

    Returns:
        The parsed feedparser result (has `.bozo`, `.entries`, optionally `.status`).

    Raises:
        RSSFetchError: If the fetch fails or times out.
    """
    try:
        logger.info(f"Fetching RSS feed: {feed_url}")

        # Re-check at fetch time: the host was public when the feed was saved, but DNS may
        # point elsewhere now. Redirects are checked hop by hop by the handler.
        await asyncio.to_thread(assert_public_url, feed_url)

        return await _run_remote_fetch(
            feedparser.parse,
            feed_url,
            agent=USER_AGENT,
            handlers=[_PublicOnlyRedirectHandler(), _TimeoutHTTPHandler(), _TimeoutHTTPSHandler()],
        )
    except Exception as e:
        logger.error(f"Failed to fetch RSS feed: {e}")
        raise RSSFetchError(f"Failed to fetch RSS feed: {str(e)}")


async def test_feed_connection(feed_url: str) -> None:
    """
    Verify that a feed URL is reachable and returns parseable RSS/Atom content.

    Used to gate feed creation/URL updates so a broken or non-feed URL is rejected up front
    instead of only surfacing errors on the next scheduled/manual refresh.

    Raises:
        RSSFetchError: If the connection fails, times out, or the response isn't a usable feed.
    """
    feed = await _fetch_and_parse(feed_url)

    status = getattr(feed, "status", None)
    if status is not None and status >= 400:
        raise RSSFetchError(f"Feed URL returned HTTP {status}")

    # `bozo` alone is too strict (feedparser sets it for minor issues on otherwise-valid
    # feeds); combined with zero entries it's a strong signal the URL isn't an RSS/Atom feed.
    if feed.bozo and not feed.entries:
        raise RSSFetchError(f"URL does not appear to be a valid RSS/Atom feed: {feed.bozo_exception}")


async def fetch_rss_feed(feed_url: str) -> List[Dict[str, Any]]:
    """
    Fetch and parse RSS feed.

    Args:
        feed_url: URL of the RSS feed

    Returns:
        List of article dictionaries

    Raises:
        RSSFetchError: If feed fetching fails
    """
    feed = await _fetch_and_parse(feed_url)

    if feed.bozo:
        logger.warning(f"RSS feed has parsing issues: {feed.bozo_exception}")

    articles = []
    for entry in feed.entries:
        try:
            # Extract article data
            article = {
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "author": _extract_author(entry),
                "published_at": None,
                "raw_content": _entry_text(entry),
                "image_url": _extract_image_url(entry),
            }

            # Parse publication date. Feeds without an explicit offset parse as
            # naive - assume UTC rather than leaving it ambiguous (aware values
            # are normalized to UTC downstream by UTCDateTime on storage).
            if hasattr(entry, "published"):
                try:
                    parsed = date_parser.parse(entry.published)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    article["published_at"] = parsed
                except Exception as e:
                    logger.warning(f"Failed to parse date: {e}")

            articles.append(article)
        except Exception as e:
            logger.error(f"Error parsing feed entry: {e}")
            continue

    logger.info(f"Successfully fetched {len(articles)} articles from RSS feed")
    return articles


def _read_robots_txt(robots_url: str) -> RobotFileParser:
    """Blocking robots.txt fetch — always run via `_run_remote_fetch`, never directly."""
    rp = RobotFileParser()
    rp.set_url(robots_url)
    opener = urllib.request.build_opener(_PublicOnlyRedirectHandler())
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=NETWORK_CALL_TIMEOUT_SECONDS) as response:
            rp.parse(response.read().decode("utf-8", errors="replace").splitlines())
    except urllib.error.HTTPError as e:
        # RFC 9309 §2.3.1.3: any 4xx means robots.txt is unavailable and crawling is allowed.
        # Not RobotFileParser.read()'s "401/403 = disallow all": bot protection 403s the robots.txt
        # request itself, which says nothing about the site's rules. 5xx keeps the default
        # (can_fetch stays False until a robots.txt was read).
        if 400 <= e.code < 500:
            rp.allow_all = True
    return rp


async def check_robots_txt(url: str) -> bool:
    """
    Check if URL is allowed by robots.txt. The file is fetched once per host and reused for
    `ROBOTS_CACHE_SECONDS` (every article of a feed shares a host, and the WordPress API check
    follows a page check on the same host seconds later).

    Args:
        url: URL to check

    Returns:
        True if allowed, False otherwise
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        cached = _ROBOTS_CACHE.get(robots_url)
        if cached and cached[0] > time.monotonic():
            rp = cached[1]
        else:
            rp = await _run_remote_fetch(_read_robots_txt, robots_url)
            if rp.allow_all or rp.mtime():  # a 5xx answer is not cached: it may be gone next time
                _ROBOTS_CACHE[robots_url] = (time.monotonic() + ROBOTS_CACHE_SECONDS, rp)
        return rp.can_fetch(ROBOTS_USER_AGENT, url)
    except Exception as e:
        logger.warning(f"Error checking robots.txt: {e}. Proceeding with caution.")
        return True  # Default to allowed if robots.txt check fails


def _extract_page_metadata(html: str) -> Tuple[Optional[str], Optional[str]]:
    """Pull the author and hero image (og:image / twitter:image) from a page's
    metadata (meta tags / JSON-LD) via trafilatura."""
    author: Optional[str] = None
    image: Optional[str] = None
    try:
        meta = extract_metadata(html)
        if meta:
            raw_author = getattr(meta, "author", None)
            if raw_author and str(raw_author).strip():
                author = str(raw_author).strip()
            raw_image = getattr(meta, "image", None)
            if raw_image and str(raw_image).strip():
                image = str(raw_image).strip()
    except Exception as e:
        logger.debug(f"Page metadata extraction failed: {e}")
    return author, image


async def _get_public_page(session, url: str, headers: Dict[str, str]
                           ) -> Tuple[Optional[int], Optional[str], str]:
    """GET `url`, following redirects one hop at a time and only to public hosts. Returns
    (status, page text, final URL); the text is None on a non-200 answer, and the status too on a
    refused redirect or too many redirects."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        async with session.get(current, headers=headers, allow_redirects=False,
                               timeout=aiohttp.ClientTimeout(total=30)) as response:
            if response.status in _REDIRECT_STATUSES:
                location = response.headers.get("Location")
                if not location:
                    logger.warning(f"HTTP {response.status} without Location for URL: {current}")
                    return None, None, current
                target = urljoin(current, location)
                if not await asyncio.to_thread(is_public_url, target):
                    logger.warning(f"Refusing redirect from {current} to a non-public address: {target}")
                    return None, None, current
                current = target
                continue
            if response.status != 200:
                logger.warning(f"HTTP {response.status} for URL: {current}")
                return response.status, None, current
            return response.status, await response.text(), current
    logger.warning(f"Too many redirects for URL: {url}")
    return None, None, current


async def _wordpress_post_text(url: str) -> Optional[str]:
    """The article text from the site's WordPress REST API (`/wp-json/wp/v2/posts?slug=…`), for
    WordPress sites whose pages are behind bot protection while the API is not (Medyascope).
    `url` is the page that refused us (after redirects), so short links resolve to the real slug.
    None when the site isn't WordPress, has no post with that slug, or blocks the API too."""
    parsed = urlparse(url)
    slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if not slug or "." in slug:
        return None
    api_url = f"{parsed.scheme}://{parsed.netloc}/wp-json/wp/v2/posts"
    try:
        if not await check_robots_txt(api_url):
            return None
        async with aiohttp.ClientSession() as session:
            status, body, _ = await _get_public_page(
                session, f"{api_url}?{urlencode({'slug': slug, '_fields': 'content'})}",
                {"User-Agent": USER_AGENT})
        if body is None:
            return None
        posts = json.loads(body)
        rendered = posts[0]["content"]["rendered"] if posts else ""
    except (ValueError, KeyError, IndexError, TypeError, aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.info(f"No WordPress API text for {url}: {e}")
        return None
    text = html_to_text(rendered)
    if text:
        logger.info(f"Read {len(text)} characters for {url} from the WordPress API")
    return text or None


async def extract_article_content(url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Extract main content, author, and hero image from an article URL using trafilatura.

    Args:
        url: URL of the article

    Returns:
        (content, author, image_url) — any element may be None if unavailable.

    Raises:
        ScrapingError: If scraping fails
    """
    if not settings.scraping_enabled:
        logger.info("Scraping is disabled in settings")
        return None, None, None

    if not await asyncio.to_thread(is_public_url, url):
        logger.warning(f"Refusing to fetch article on a non-public address: {url}")
        return None, None, None

    try:
        # Check robots.txt
        if not await check_robots_txt(url):
            logger.warning(f"URL not allowed by robots.txt: {url}")
            return None, None, None

        logger.info(f"Extracting content from: {url}")

        # Be polite to the source server: wait between scrape requests.
        if settings.scraping_delay > 0:
            await asyncio.sleep(settings.scraping_delay)

        # Fetch the page with custom user agent
        headers = {"User-Agent": USER_AGENT}

        html: Optional[str] = None
        attempts = max(1, settings.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    status, html, final_url = await _get_public_page(session, url, headers)
                if html is None:
                    if status in _BLOCKED_STATUSES:
                        return await _wordpress_post_text(final_url), None, None
                    return None, None, None
                break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt >= attempts:
                    raise
                logger.warning(f"Transient error fetching {url} (attempt {attempt}/{attempts}): {e}. Retrying...")
                await asyncio.sleep(settings.scraping_delay)

        # Author and hero image from page metadata — RSS feeds (e.g. DW) often omit both
        author, image_url = _extract_page_metadata(html)

        # Extract content using trafilatura
        content = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            no_fallback=False
        )

        if content:
            logger.info(f"Successfully extracted {len(content)} characters from {url}")
        else:
            logger.warning(f"No content extracted from {url}")

        return content, author, image_url

    except aiohttp.ClientError as e:
        logger.error(f"HTTP error while fetching {url}: {e}")
        raise ScrapingError(f"HTTP error: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to extract content from {url}: {e}")
        raise ScrapingError(f"Content extraction failed: {str(e)}")


_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Collapse embedded HTML markup down to plain text.

    raw_content is the RSS <description>, which for several feeds (e.g.
    Aydinlik) is itself an HTML fragment (<a>/<img>/<h4>/<div> tags) rather
    than plain text. cleaned_content falls back to that same raw_content
    verbatim when article scraping fails (see agents/nodes.py), so without
    this the markup — and HTML entities like &#039; — leaked straight into
    the rendered bulletin as visible text.

    Uses a real HTML parser (not a "<[^>]+>" regex) so literal bracketed text
    that isn't actually markup, e.g. "büyüme <10 yaş grubunda> daha hızlı",
    isn't mistaken for a tag and deleted."""
    plain = BeautifulSoup(text, "html.parser").get_text(separator=" ")
    return _WHITESPACE_RE.sub(" ", unescape(plain)).strip()


_BLOCK_TAGS = ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "br", "tr",
               "figcaption")


# WordPress appends "The post <title> appeared first on <site>." to every feed item.
_WP_FEED_FOOTER_RE = re.compile(r"^The post .+ appeared first on .+\.?$")


def html_to_text(html: str) -> str:
    """An article body's HTML (feed <content:encoded>, WordPress `content.rendered`) as plain text
    with one paragraph per line — the shape trafilatura gives scraped pages, which the "Orijinal
    İçerik" view splits into paragraphs. Unlike `strip_html`, which flattens to a single line.

    Line breaks come only from block tags: whitespace (newlines included) inside the source HTML
    is collapsed per text node first. The parser already decodes entities — no second unescape."""
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    for node in soup.find_all(string=True):
        if isinstance(node, Comment):
            node.extract()
        else:
            node.replace_with(_WHITESPACE_RE.sub(" ", str(node)))
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (line.strip() for line in soup.get_text().split("\n"))
    return "\n".join(line for line in lines if line and not _WP_FEED_FOOTER_RE.match(line))


def truncate_content(content: str, max_tokens: int = 4000) -> str:
    """
    Truncate content to approximately max_tokens.
    Simple approximation: 1 token ≈ 4 characters.
    
    Args:
        content: Text content to truncate
        max_tokens: Maximum number of tokens
        
    Returns:
        Truncated content
    """
    max_chars = max_tokens * 4
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."
