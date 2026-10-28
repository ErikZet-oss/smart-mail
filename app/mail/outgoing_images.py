"""Rewrite outgoing ``<img>`` sources when building MIME (issue #31).

Gmail and Outlook do not show ``data:`` images, SVG, or relative app paths
(``/logo-smart.svg``, ``/api/settings/signature-images/…``). The settings preview
may still use those. Send turns the ones we can honour into CID parts or an
``https://`` URL, and drops the rest.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import html
import re
from collections.abc import Mapping
from urllib.parse import parse_qs, urlparse

from app.mail.signature import LOGO_CID
from app.mail.signature_images import MAX_SIGNATURE_IMAGE_BYTES

_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[a-zA-Z][^>]*>")
# ``src`` is a whole attribute name. ``\b`` is true between ``-`` and ``s``, so
# ``data-sm-keep-src`` and ``data-src`` must not count. ``srcset`` is not ``src``.
_SRC = re.compile(
    r"""(?<![\w-])src(?![\w-])(?:\s*=\s*(?:(?P<q>["'])(?P<url>[^"']*)(?P=q)|(?P<bare>[^\s>"']*)))?""",
    re.IGNORECASE,
)
_INTERNAL_ATTR = re.compile(
    r"""\s+(?:data-sm-[\w-]*|data-cid)\b(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>]*))?""",
    re.IGNORECASE,
)
_SRCSET = re.compile(
    r"""\s+srcset\b(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>]*))?""",
    re.IGNORECASE,
)
_DATA = re.compile(
    r"^data:image/(?P<kind>png|jpe?g|gif|webp)(?:;[^,]*)?;base64,(?P<b64>[a-z0-9+/=\s]+)$",
    re.IGNORECASE,
)
_LOGO_PATH = re.compile(r"^/logo-smart\.(?:svg|png)$", re.IGNORECASE)
_UPLOAD_PATH = re.compile(r"^/api/settings/signature-images/(?P<id>[A-Za-z0-9_-]+)/?$", re.IGNORECASE)
_KINDS = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


def looks_like_svg(data: bytes) -> bool:
    head = data.lstrip()[:200].lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2000].lower())


def sniff_raster(data: bytes) -> str | None:
    """PNG, JPEG, GIF or WebP. SVG and anything else are not mail images."""
    if not data or looks_like_svg(data):
        return None
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _data_cid(data: bytes) -> str:
    return f"img-{hashlib.sha256(data).hexdigest()[:16]}@smartmail"


def _safe_https(url: str) -> bool:
    if len(url) > 2048 or any(ch in url for ch in " \t\r\n\"'<>"):
        return False
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


class _Parts:
    def __init__(self, logo_png: bytes | None, images_by_id: Mapping[str, tuple[str, bytes, str]]) -> None:
        self.logo_png = logo_png if logo_png and sniff_raster(logo_png) == "image/png" else None
        self.images_by_id = images_by_id
        self.blobs: list[tuple[str, bytes, str]] = []
        self._seen: set[str] = set()
        self.stripped = 0

    def add(self, cid: str, data: bytes) -> bool:
        sniffed = sniff_raster(data)
        if sniffed is None:
            return False
        key = cid.lower()
        if key in self._seen:
            return True
        self._seen.add(key)
        self.blobs.append((cid, data, sniffed))
        return True


def _replace_src(tag: str, match: re.Match[str], url: str) -> str:
    quote = match.group("q")
    safe = html.escape(url, quote=True)
    return tag[: match.start()] + f"src={quote}{safe}{quote}" + tag[match.end() :]


def _blank_src(tag: str, match: re.Match[str]) -> str:
    quote = match.group("q") or '"'
    return tag[: match.start()] + f"src={quote}{quote}" + tag[match.end() :]


def _strip_internal(html_body: str) -> str:
    """Drop stamps and ``srcset`` from the MIME copy. The HMAC must not leave."""

    def repl(match: re.Match[str]) -> str:
        tag = _INTERNAL_ATTR.sub("", match.group(0))
        if tag.lower().startswith("<img"):
            tag = _SRCSET.sub("", tag)
        return tag

    return _TAG.sub(repl, html_body)


def _cid_of(raw: str) -> str:
    return raw[4:].strip().strip("<>").strip()


def _from_data(raw: str, parts: _Parts) -> str:
    if len(raw) > MAX_SIGNATURE_IMAGE_BYTES * 2:
        return ""
    matched = _DATA.match(raw.strip())
    if matched is None:
        return ""
    expected = _KINDS[matched.group("kind").lower()]
    try:
        data = base64.b64decode(re.sub(r"\s+", "", matched.group("b64")), validate=True)
    except (binascii.Error, ValueError):
        return ""
    if not data or len(data) > MAX_SIGNATURE_IMAGE_BYTES or sniff_raster(data) != expected:
        return ""
    cid = _data_cid(data)
    if not parts.add(cid, data):
        return ""
    return f"cid:{cid}"


def _from_proxy(query: str) -> str:
    if not query:
        return ""
    values = parse_qs(query, keep_blank_values=False, max_num_fields=8)
    remote = (values.get("u") or [""])[0].strip()
    if remote.lower().startswith("https://") and _safe_https(remote):
        return remote
    return ""


def _decide(raw: str, parts: _Parts) -> str | None:
    """None keeps the src. ``""`` clears it. Any other string replaces it."""
    if not raw:
        return ""
    lower = raw.lower()
    if lower.startswith("https://"):
        return None if _safe_https(raw) else ""
    if lower.startswith("cid:"):
        cid = _cid_of(raw)
        if cid.lower() == LOGO_CID.lower() and parts.logo_png is not None:
            parts.add(LOGO_CID, parts.logo_png)
        return None
    if lower.startswith("data:"):
        return _from_data(raw, parts)
    path, _, query = raw.split("#", 1)[0].partition("?")
    if _LOGO_PATH.match(path):
        if parts.logo_png is None or not parts.add(LOGO_CID, parts.logo_png):
            return ""
        return f"cid:{LOGO_CID}"
    upload = _UPLOAD_PATH.match(path)
    if upload is not None:
        rec = parts.images_by_id.get(upload.group("id"))
        if rec is None:
            return ""
        cid, data, _ctype = rec
        if not parts.add(cid, data):
            return ""
        return f"cid:{cid}"
    if path.lower() == "/api/mail/image-proxy":
        return _from_proxy(query)
    return ""


def normalize_outgoing_images(
    html_body: str,
    *,
    logo_png: bytes | None,
    images_by_id: Mapping[str, tuple[str, bytes, str]] | None = None,
) -> tuple[str, list[tuple[str, bytes, str]], int]:
    """Return ``(html, related parts, stripped count)``.

    Related parts are ``(cid, bytes, image/*)``. The count is how many images
    were cleared (``http://``, empty src, SVG, or any other src we will not send).
    """
    parts = _Parts(logo_png, images_by_id or {})

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src = _SRC.search(tag)
        if src is None:
            return tag
        # Unquoted ``src=value``, ``src=`` and a bare ``src`` are cleared.
        # The value is not read, so a relative path or ``data:`` cannot leave.
        if src.group("q") is None:
            parts.stripped += 1
            return _blank_src(tag, src)
        raw = html.unescape(src.group("url") or "").strip()
        action = _decide(raw, parts)
        if action is None:
            return tag
        if action == "":
            parts.stripped += 1
            return _blank_src(tag, src)
        return _replace_src(tag, src, action)

    rewritten = _IMG.sub(repl, html_body or "")
    return _strip_internal(rewritten), parts.blobs, parts.stripped
