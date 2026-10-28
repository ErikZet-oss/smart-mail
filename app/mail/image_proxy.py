"""Signed same-origin image proxy for remote mail images (pilot #18 B6).

CSP keeps img-src without https:; the reading pane loads remotes only through this endpoint.
HMAC is minted by the server when rendering a message — the proxy is not an open relay.

Security (Erik review on PR #22):
- Resolve DNS with async getaddrinfo, then **pin** the TCP/TLS connection to that IP (Host + SNI kept)
  so a later rebinding answer cannot steer the request at Docker/private addresses.
- Block any address that is not globally routable (`not ip.is_global`), including CGNAT and
  IPv4-mapped forms via `ip.ipv4_mapped`.
- Stream the body and abort after PROXY_MAX_BYTES; reject oversized Content-Length up front.
- Signing key is purpose-derived: HMAC(APP_SECRET_KEY, "image-proxy"), never the raw secret.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

PROXY_TIMEOUT_S = 5.0
DNS_TIMEOUT_S = 3.0
PROXY_MAX_BYTES = 5 * 1024 * 1024
_PURPOSE = b"image-proxy"
_MAX_REDIRECTS = 3


class ImageProxyError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class PinnedTarget:
    """Validated remote target with a single DNS-pinned connect address."""

    scheme: str
    host: str
    port: int
    path: str
    query: str
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address

    @property
    def path_and_query(self) -> str:
        return f"{self.path}?{self.query}" if self.query else self.path

    @property
    def normalized_url(self) -> str:
        default = (self.scheme == "https" and self.port == 443) or (self.scheme == "http" and self.port == 80)
        authority = self.host if default else f"{self.host}:{self.port}"
        return f"{self.scheme}://{authority}{self.path_and_query}"

    @property
    def host_header(self) -> str:
        default = (self.scheme == "https" and self.port == 443) or (self.scheme == "http" and self.port == 80)
        return self.host if default else f"{self.host}:{self.port}"

    @property
    def connect_url(self) -> str:
        """URL whose host is the pinned IP (connection target); Host/SNI stay on ``host``."""
        if self.ip.version == 6:
            authority = f"[{self.ip}]:{self.port}"
        else:
            authority = f"{self.ip}:{self.port}"
        return f"{self.scheme}://{authority}{self.path_and_query}"


def _signing_key(settings: Settings) -> bytes:
    """Purpose-separated key: HMAC(APP_SECRET_KEY, \"image-proxy\")."""
    secret = settings.app_secret_key.get_secret_value().encode("utf-8")
    return hmac.new(secret, _PURPOSE, hashlib.sha256).digest()


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
    """True when the address must not be contacted (SSRF). Prefer ``not is_global`` over allowlists."""
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        # ::ffff:127.0.0.1 is not is_loopback on Python 3.12 — unwrap and re-check.
        return is_blocked_ip(ip.ipv4_mapped)
    return not ip.is_global


def _parse_http_url(url: str) -> tuple[str, str, int, str, str]:
    raw = (url or "").strip()
    if not raw or len(raw) > 2048:
        raise ImageProxyError("invalid_url", 400)
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ImageProxyError("invalid_scheme", 400)
    host = parsed.hostname
    if not host:
        raise ImageProxyError("invalid_url", 400)
    if parsed.username or parsed.password:
        raise ImageProxyError("invalid_url", 400)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    query = parsed.query or ""
    return parsed.scheme, host, port, path, query


def assert_public_http_url(url: str) -> tuple[str, str, int]:
    """Validate scheme/host; for literal IP hosts enforce SSRF policy (sync, no DNS).

    Hostname URLs are only structurally checked here — callers that fetch must use
    ``await pin_http_url`` so DNS is async and the connect IP is pinned.
    """
    scheme, host, port, path, query = _parse_http_url(url)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and is_blocked_ip(literal):
        raise ImageProxyError("ssrf_blocked", 400)
    default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    authority = host if default else f"{host}:{port}"
    pq = f"{path}?{query}" if query else path
    return f"{scheme}://{authority}{pq}", host, port


async def resolve_public_ip(host: str, port: int) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    """Async DNS with timeout; every answer must be globally routable; return the first."""
    loop = asyncio.get_running_loop()
    try:
        async with asyncio.timeout(DNS_TIMEOUT_S):
            infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except TimeoutError as exc:
        raise ImageProxyError("dns_timeout", 400) from exc
    except OSError as exc:
        raise ImageProxyError("dns_failed", 400) from exc
    if not infos:
        raise ImageProxyError("dns_failed", 400)
    chosen: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if is_blocked_ip(ip):
            raise ImageProxyError("ssrf_blocked", 400)
        if chosen is None:
            chosen = ip
    if chosen is None:
        raise ImageProxyError("dns_failed", 400)
    return chosen


async def pin_http_url(url: str) -> PinnedTarget:
    """Parse URL, resolve hostname once, pin the connect IP (DNS-rebinding safe)."""
    scheme, host, port, path, query = _parse_http_url(url)
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_ip(literal):
            raise ImageProxyError("ssrf_blocked", 400)
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address = literal
    else:
        ip = await resolve_public_ip(host, port)
    return PinnedTarget(scheme=scheme, host=host, port=port, path=path, query=query, ip=ip)


async def _read_limited_body(response: httpx.Response) -> bytes:
    """Stream the response; reject oversized Content-Length or bodies over PROXY_MAX_BYTES."""
    cl_raw = response.headers.get("content-length")
    if cl_raw is not None:
        try:
            content_length = int(cl_raw)
        except ValueError:
            content_length = -1
        if content_length > PROXY_MAX_BYTES:
            raise ImageProxyError("too_large", 413)
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > PROXY_MAX_BYTES:
            raise ImageProxyError("too_large", 413)
        chunks.append(chunk)
    return b"".join(chunks)


async def _request_pinned(client: httpx.AsyncClient, target: PinnedTarget) -> httpx.Response:
    """GET via the pinned IP; Host + SNI stay on the original hostname."""
    headers = {
        "Host": target.host_header,
        "User-Agent": "SmartMail-ImageProxy/1.0",
        "Accept": "image/*",
    }
    request = client.build_request("GET", target.connect_url, headers=headers)
    # Pin TLS SNI / cert name to the original host while connecting to the verified IP.
    request.extensions["sni_hostname"] = target.host
    return await client.send(request, stream=True)


async def fetch_proxied_image(settings: Settings, url: str, sig: str) -> tuple[bytes, str]:
    """Verify signature, SSRF-check with DNS pin, stream-fetch; return (body, content_type)."""
    decoded = unquote(url)
    if verify_image_sig(settings, decoded, sig):
        signed_url = decoded
    elif verify_image_sig(settings, url, sig):
        signed_url = url
    else:
        raise ImageProxyError("bad_signature", 403)

    target = await pin_http_url(signed_url)
    response: httpx.Response | None = None
    try:
        async with httpx.AsyncClient(
            timeout=PROXY_TIMEOUT_S,
            follow_redirects=False,
            cookies={},
            trust_env=False,
        ) as client:
            hops = 0
            while True:
                response = await _request_pinned(client, target)
                if response.is_redirect and hops < _MAX_REDIRECTS:
                    location = response.headers.get("location")
                    await response.aclose()
                    response = None
                    hops += 1
                    if not location:
                        raise ImageProxyError("upstream_error", 502)
                    # Relative redirect → absolute against the logical (hostname) URL.
                    location = urljoin(target.normalized_url, location)
                    # Re-pin on every hop (DNS + SSRF again; never reuse unbound hostname resolve).
                    target = await pin_http_url(location)
                    continue
                break

            assert response is not None
            if response.status_code >= 400:
                await response.aclose()
                raise ImageProxyError("upstream_error", 502)
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                await response.aclose()
                raise ImageProxyError("not_image", 415)
            if content_type in {"image/svg+xml", "image/svg"}:
                await response.aclose()
                raise ImageProxyError("svg_forbidden", 415)
            try:
                body = await _read_limited_body(response)
            finally:
                await response.aclose()
            return body, content_type
    except ImageProxyError:
        raise
    except Exception as exc:
        log.warning("image_proxy.fetch_failed", error=type(exc).__name__)
        raise ImageProxyError("fetch_failed", 502) from exc
