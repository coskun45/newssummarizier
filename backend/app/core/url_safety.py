"""
SSRF guard for user-supplied feed URLs.

Feed URLs are fetched server-side (feedparser/aiohttp) once created, so a URL pointing at an
internal host or the cloud metadata endpoint would let an authenticated user make the backend
issue requests to hosts it shouldn't reach. Resolve the hostname and reject anything that lands
on a private, loopback, link-local, or otherwise non-public address before the feed is stored.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException, status


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


def assert_safe_feed_url(url: str) -> None:
    """Raise HTTPException(400) if `url` resolves to a non-public address."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid feed URL")

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed URL host could not be resolved",
        )

    resolved_ips = {info[4][0] for info in addrinfo}
    if not resolved_ips or not all(_is_public_ip(ip) for ip in resolved_ips):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed URL resolves to a non-public address and is not allowed",
        )
