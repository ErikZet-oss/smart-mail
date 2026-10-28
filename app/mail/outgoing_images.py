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
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.mail.signature import LOGO_CID
from app.mail.signature_images import MAX_SIGNATURE_IMAGE_BYTES

_WS = " \t\r\n"
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


@dataclass(frozen=True)
class _Attr:
    """One attribute. ``source`` is the original text, including the leading space."""

    name: str
    leading: str
    had_equals: bool
    quoted: bool
    quote: str
    value: str
    source: str


def _is_internal(name: str, *, img: bool) -> bool:
    lower = name.lower()
    if lower == "data-cid" or lower.startswith("data-sm-"):
        return True
    return img and lower == "srcset"


def _parse_tag(text: str, start: int) -> tuple[str, list[_Attr], str, int] | None:
    """Tokenize one start tag. ``None`` when the attribute list is not clean.

    Attributes are read left to right. A value is only the quoted or unquoted
    token after ``=``, never a later attribute and never text inside another value.
    """
    if start >= len(text) or text[start] != "<":
        return None
    i = start + 1
    if i >= len(text) or not text[i].isalpha():
        return None
    j = i + 1
    while j < len(text) and text[j] not in _WS and text[j] not in "/>":
        j += 1
    name = text[i:j]
    i = j
    attrs: list[_Attr] = []
    while i < len(text):
        k = i
        while i < len(text) and text[i] in _WS:
            i += 1
        if i >= len(text):
            return None
        if text[i] == ">":
            return name, attrs, text[k : i + 1], i + 1
        if text[i] == "/" and i + 1 < len(text) and text[i + 1] == ">":
            return name, attrs, text[k : i + 2], i + 2
        if not text[k:i]:
            return None
        leading = text[k:i]
        name_at = i
        while i < len(text) and text[i] not in _WS and text[i] not in "=/>":
            i += 1
        if i == name_at:
            return None
        attr_name = text[name_at:i]
        m = i
        while i < len(text) and text[i] in _WS:
            i += 1
        had_equals = i < len(text) and text[i] == "="
        quoted = False
        quote = ""
        value = ""
        if had_equals:
            i += 1
            while i < len(text) and text[i] in _WS:
                i += 1
            if i >= len(text):
                return None
            if text[i] in "\"'":
                quote = text[i]
                i += 1
                vstart = i
                while i < len(text) and text[i] != quote:
                    i += 1
                if i >= len(text):
                    return None
                value = text[vstart:i]
                quoted = True
                i += 1
            else:
                vstart = i
                while i < len(text) and text[i] not in _WS and text[i] != ">":
                    if text[i] == "/" and i + 1 < len(text) and text[i + 1] == ">":
                        break
                    i += 1
                value = text[vstart:i]
        else:
            i = m
        attrs.append(
            _Attr(
                name=attr_name,
                leading=leading,
                had_equals=had_equals,
                quoted=quoted,
                quote=quote,
                value=value,
                source=text[k:i],
            )
        )
    return None


def _render_tag(name: str, attrs: list[_Attr], closer: str) -> str:
    return f"<{name}" + "".join(attr.source for attr in attrs) + closer


def _src_source(attr: _Attr, url: str) -> str:
    """Quoted ``src`` keeps its quote. Anything else is cleared and not interpreted."""
    if attr.quoted:
        safe = html.escape(url, quote=True)
        return f"{attr.leading}{attr.name}={attr.quote}{safe}{attr.quote}"
    return f'{attr.leading}src=""'


def _img_open(text: str, start: int) -> bool:
    if text[start : start + 4].lower() != "<img":
        return False
    end = start + 4
    return end == len(text) or text[end] in _WS or text[end] in "/>"


def _fallback_end(text: str, start: int) -> int | None:
    i = start + 1
    quote = ""
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            continue
        if ch == ">":
            return i + 1
        i += 1
    return None


def _rewrite_attrs(name: str, attrs: list[_Attr], parts: _Parts) -> list[_Attr]:
    img = name.lower() == "img"
    rewritten: list[_Attr] = []
    for attr in attrs:
        if img and attr.name.lower() == "src":
            if not attr.had_equals or not attr.quoted:
                parts.stripped += 1
                rewritten.append(_Attr("src", attr.leading, True, True, '"', "", f'{attr.leading}src=""'))
                continue
            action = _decide(html.unescape(attr.value).strip(), parts)
            if action is None:
                rewritten.append(attr)
                continue
            if action == "":
                parts.stripped += 1
            rewritten.append(
                _Attr(attr.name, attr.leading, True, True, attr.quote or '"', action, _src_source(attr, action))
            )
            continue
        if _is_internal(attr.name, img=img):
            continue
        rewritten.append(attr)
    return rewritten


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
    body = html_body or ""
    out: list[str] = []
    i = 0
    while i < len(body):
        if body[i] == "<" and i + 1 < len(body) and body[i + 1].isalpha():
            parsed = _parse_tag(body, i)
            if parsed is None:
                if _img_open(body, i):
                    end = _fallback_end(body, i)
                    out.append('<img src="">')
                    parts.stripped += 1
                    if end is None:
                        break
                    i = end
                    continue
                out.append(body[i])
                i += 1
                continue
            name, attrs, closer, end = parsed
            changed = name.lower() == "img" or any(_is_internal(attr.name, img=False) for attr in attrs)
            if changed:
                out.append(_render_tag(name, _rewrite_attrs(name, attrs, parts), closer))
            else:
                out.append(body[i:end])
            i = end
            continue
        out.append(body[i])
        i += 1
    return "".join(out), parts.blobs, parts.stripped
