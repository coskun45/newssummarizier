"""
SSRF guard for URLs the backend fetches server-side (feeds, the articles they link to, and every
redirect hop on the way).

A URL pointing at an internal host or the cloud metadata endpoint would let a feed make the backend
issue requests to hosts it shouldn't reach. Resolve the hostname and reject anything that lands on a
private, loopback, link-local, or otherwise non-public address. The check runs when a feed is saved
AND again right before every fetch — DNS can change after the feed was stored (rebinding), and a
feed's article links were never checked at save time.
"""
import ipaddress
import socket
from typing import Set
from urllib.parse import urlparse

from fastapi import HTTPException, status

ALLOWED_SCHEMES = ("http", "https")


class UnsafeURLError(ValueError):
    """The URL is not http(s) or its host resolves to a non-public address."""


class UnresolvableURLError(UnsafeURLError):
    """The URL's host does not resolve."""


def _is_public_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_host(hostname: str) -> Set[str]:
    """All addresses `hostname` resolves to (blocking DNS lookup). Raises socket.gaierror."""
    return {info[4][0] for info in socket.getaddrinfo(hostname, None)}


def assert_public_url(url: str) -> None:
    """Raise UnsafeURLError unless `url` is http(s) and its host resolves only to public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        raise UnsafeURLError("Invalid URL")
    try:
        resolved_ips = _resolve_host(parsed.hostname)
    except (socket.gaierror, UnicodeError):
        raise UnresolvableURLError("URL host could not be resolved")
    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise UnsafeURLError("URL resolves to a non-public address and is not allowed")


def is_public_url(url: str) -> bool:
    try:
        assert_public_url(url)
    except UnsafeURLError:
        return False
    return True


def assert_safe_feed_url(url: str) -> None:
    """Route-level guard: raise HTTPException(400) if `url` resolves to a non-public address."""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid feed URL")
    try:
        assert_public_url(url)
    except UnresolvableURLError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Feed URL host could not be resolved")
    except UnsafeURLError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed URL resolves to a non-public address and is not allowed",
        )
