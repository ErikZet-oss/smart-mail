"""Signed same-origin image proxy for remote mail images (pilot #18 B6).

CSP keeps img-src without https:; the reading pane loads remotes only through this endpoint.
HMAC is minted by the server when rendering a message — the proxy is not an open relay.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import socket
from urllib.parse import quote, unquote, urlparse

import httpx
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

PROXY_TIMEOUT_S = 5.0
PROXY_MAX_BYTES = 5 * 1024 * 1024
_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


class ImageProxyError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _signing_key(settings: Settings) -> bytes:
    return settings.app_secret_key.get_secret_value().encode("utf-8")


def sign_image_url(settings: Settings, url: str) -> str:
    """HMAC-SHA256 hex digest over the exact remote URL string."""
    return hmac.new(_signing_key(settings), url.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_image_sig(settings: Settings, url: str, sig: str) -> bool:
    expected = sign_image_url(settings, url)
    return hmac.compare_digest(expected, (sig or "").strip().lower())


def proxy_path(settings: Settings, url: str) -> str:
    """Same-origin path the reading pane may put in img src (CSP img-src 'self')."""
    sig = sign_image_url(settings, url)
    return f"/api/mail/image-proxy?u={quote(url, safe='')}&sig={sig}"


def is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
        return True
    if ip.is_unspecified:
        return True
    for net in _BLOCKED_NETWORKS:
        if ip in net:
            return True
    return False


def assert_public_http_url(url: str) -> tuple[str, str, int]:
    """Validate scheme/host and resolve DNS; raise ImageProxyError on SSRF candidates.

    Returns (normalized_url, hostname, port).
    """
    raw = (url or "").strip()
    if not raw or len(raw) > 2048:
        raise ImageProxyError("invalid_url", 400)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ImageProxyError("invalid_scheme", 400)
    host = parsed.hostname
    if not host:
        raise ImageProxyError("invalid_url", 400)
    # Reject credentials in the URL
    if parsed.username or parsed.password:
        raise ImageProxyError("invalid_url", 400)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Literal IP host
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and is_blocked_ip(literal):
        raise ImageProxyError("ssrf_blocked", 400)

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImageProxyError("dns_failed", 400) from exc
    if not infos:
        raise ImageProxyError("dns_failed", 400)
    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if is_blocked_ip(ip):
            raise ImageProxyError("ssrf_blocked", 400)

    # Rebuild without fragment; keep query
    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    normalized = (
        f"{parsed.scheme}://{host}:{port}{path}{query}" if parsed.port else f"{parsed.scheme}://{host}{path}{query}"
    )
    return normalized, host, port


async def fetch_proxied_image(settings: Settings, url: str, sig: str) -> tuple[bytes, str]:
    """Verify signature, SSRF-check, fetch; return (body, content_type)."""
    decoded = unquote(url)
    if not verify_image_sig(settings, decoded, sig) and not verify_image_sig(settings, url, sig):
        # Accept either raw or already-decoded form as signed payload
        raise ImageProxyError("bad_signature", 403)
    signed_url = decoded if verify_image_sig(settings, decoded, sig) else url
    normalized, _host, _port = assert_public_http_url(signed_url)

    try:
        async with httpx.AsyncClient(
            timeout=PROXY_TIMEOUT_S,
            follow_redirects=False,
            headers={"User-Agent": "SmartMail-ImageProxy/1.0", "Accept": "image/*"},
            cookies={},
            trust_env=False,
        ) as client:
            # No Referer; no cookies (empty). Manual redirect check to re-validate SSRF.
            response = await client.get(normalized)
            hops = 0
            while response.is_redirect and hops < 3:
                hops += 1
                location = response.headers.get("location")
                if not location:
                    break
                nxt = urlparse(location)
                if not nxt.scheme:
                    # relative redirect
                    base = urlparse(normalized)
                    location = f"{base.scheme}://{base.netloc}{location}"
                normalized, _, _ = assert_public_http_url(location)
                response = await client.get(normalized)
    except ImageProxyError:
        raise
    except Exception as exc:
        log.warning("image_proxy.fetch_failed", error=type(exc).__name__)
        raise ImageProxyError("fetch_failed", 502) from exc

    if response.status_code >= 400:
        raise ImageProxyError("upstream_error", 502)
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if not content_type.startswith("image/"):
        raise ImageProxyError("not_image", 415)
    if content_type in {"image/svg+xml", "image/svg"}:
        raise ImageProxyError("svg_forbidden", 415)
    body = response.content
    if len(body) > PROXY_MAX_BYTES:
        raise ImageProxyError("too_large", 413)
    return body, content_type
