"""
Tools for the news processing agents.
"""
import asyncio
import feedparser
import trafilatura
from trafilatura.metadata import extract_metadata
import aiohttp
import logging
from datetime import timezone
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from dateutil import parser as date_parser
from app.core.config import settings
from app.core.exceptions import RSSFetchError, ScrapingError

logger = logging.getLogger(__name__)

# Both feedparser and RobotFileParser do blocking, timeout-less network I/O under the hood.
# Run them in a worker thread so a stalled remote server can't freeze the FastAPI event loop,
# and bound them with an explicit timeout so a hang doesn't stall the caller indefinitely.
NETWORK_CALL_TIMEOUT_SECONDS = 30


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

        # feedparser.parse() is a blocking, timeout-less network call — run it off the event
        # loop and bound it so a stalled feed server can't hang the whole app.
        return await asyncio.wait_for(
            asyncio.to_thread(feedparser.parse, feed_url),
            timeout=NETWORK_CALL_TIMEOUT_SECONDS,
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
                "raw_content": entry.get("description", "") or entry.get("summary", ""),
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


def _read_robots_txt(robots_url: str, url: str) -> bool:
    """Blocking robots.txt fetch + check — always run via asyncio.to_thread, never directly."""
    rp = RobotFileParser()
    rp.set_url(robots_url)
    rp.read()

    user_agent = "NewsSummarizer/1.0"
    return rp.can_fetch(user_agent, url)


async def check_robots_txt(url: str) -> bool:
    """
    Check if URL is allowed by robots.txt.

    Args:
        url: URL to check

    Returns:
        True if allowed, False otherwise
    """
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        # RobotFileParser.read() is a blocking, timeout-less network call — run it off the
        # event loop and bound it so a stalled/unreachable robots.txt host can't hang the app.
        return await asyncio.wait_for(
            asyncio.to_thread(_read_robots_txt, robots_url, url),
            timeout=NETWORK_CALL_TIMEOUT_SECONDS,
        )
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
        headers = {
            "User-Agent": "NewsSummarizer/1.0 (+https://github.com/yourusername/news-summary)"
        }

        html: Optional[str] = None
        attempts = max(1, settings.max_retries)
        for attempt in range(1, attempts + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as response:
                        if response.status != 200:
                            logger.warning(f"HTTP {response.status} for URL: {url}")
                            return None, None, None
                        html = await response.text()
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
