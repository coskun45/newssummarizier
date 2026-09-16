"""
Tests for app/agents/tools.py — pure helpers only (network-bound functions
like fetch_rss_feed/extract_article_content aren't covered here).
"""
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
