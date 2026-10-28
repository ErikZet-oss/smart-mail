"""HTML sanitizer for message bodies (CLAUDE.md §5 / §14, SCREENS_SPEC W2c).

Remote http(s) images are replaced with a marker so the reading pane can show "Zobraziť obrázky"; cid: and data:
images stay (inline signature images, DECISIONS D22).
"""

from __future__ import annotations

import re
from typing import Final

import nh3

REMOTE_PLACEHOLDER: Final = "about:blank#smartmail-remote"
_MAX_DEFAULT = 512_000

# Tags Roundcube-style mail needs; no script/iframe/form/object/embed/base/meta.
_TAGS: Final = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "q",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

_ATTRS: Final = {
    "*": {"class", "style", "title", "dir", "lang"},
    "a": {"href", "name", "target"},
    "img": {"src", "alt", "width", "height", "data-cid", "data-sm-keep-src"},
    "td": {"colspan", "rowspan", "align", "valign", "width", "height"},
    "th": {"colspan", "rowspan", "align", "valign", "width", "height"},
    "col": {"span", "width"},
    "colgroup": {"span"},
    "table": {"width", "border", "cellpadding", "cellspacing", "align"},
}

_URL_SCHEMES: Final = {"http", "https", "mailto", "cid", "data"}
_REMOTE_SRC = re.compile(
    r'(?P<pre><img\b[^>]*?\bsrc\s*=\s*)(?P<q>["\'])(?P<url>https?://[^"\']+)(?P=q)',
    re.IGNORECASE,
)


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_DANGER_TAGS = ("script", "iframe", "form", "input", "object", "embed", "base", "meta", "textarea", "button", "svg")
# https images in a signature stay (D22). Message bodies still rewrite remote images.
_KEEP_SRC = re.compile(r"data-sm-keep-src\s*=", re.IGNORECASE)
_IMG_SRC = re.compile(r"""\bsrc\s*=\s*(?P<q>["'])(?P<url>[^"']*)(?P=q)""", re.IGNORECASE)
_ALLOWED_SIG_SRC = re.compile(
    r"^(https://|cid:|data:image/(?:png|jpeg|gif|webp);|/api/settings/signature-images/|/api/mail/image-proxy\?|/logo-smart\.)",
    re.IGNORECASE,
)


def _rewrite_remote_imgs(html: str) -> str:
    def repl_src(match: re.Match[str]) -> str:
        q = match.group("q")
        url = match.group("url")
        return f"{match.group('pre')}{q}{REMOTE_PLACEHOLDER}{q} data-remote-src={q}{url}{q}"

    def repl_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        if _KEEP_SRC.search(tag):
            return tag
        return _REMOTE_SRC.sub(repl_src, tag)

    return _IMG_TAG.sub(repl_tag, html)


def _mark_signature_urls(html: str) -> str:
    """Mark https signature images so a later message sanitise does not turn them into placeholders."""

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src = _IMG_SRC.search(tag)
        if src is None or not src.group("url").lower().startswith("https://") or _KEEP_SRC.search(tag):
            return tag
        return tag[:-1] + ' data-sm-keep-src="1">'

    return _IMG_TAG.sub(repl, html)


def _drop_disallowed_signature_src(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        src = _IMG_SRC.search(tag)
        if src is None:
            return tag
        url = src.group("url").strip()
        if not url or _ALLOWED_SIG_SRC.match(url):
            return tag
        q = src.group("q")
        return tag[: src.start()] + f"src={q}{q}" + tag[src.end() :]

    return _IMG_TAG.sub(repl, html)


def signature_stripped_parts(original: str, cleaned: str) -> list[str]:
    """Names of dangerous constructs that were in the input and are gone after nh3."""
    original_l = original.lower()
    cleaned_l = cleaned.lower()
    gone: list[str] = []
    for tag in _DANGER_TAGS:
        if re.search(rf"<{tag}\b", original_l) and not re.search(rf"<{tag}\b", cleaned_l):
            gone.append(f"<{tag}>")
    if re.search(r"\son[a-z]+\s*=", original_l) and not re.search(r"\son[a-z]+\s*=", cleaned_l):
        gone.append("on*")
    if "javascript:" in original_l and "javascript:" not in cleaned_l:
        gone.append("javascript:")
    return gone


def sanitize_signature_html(html: str) -> tuple[str, list[str]]:
    """nh3 for signatures (D22): tables, inline styles, img. https URLs stay. No remote-image placeholder.

    Returns ``(html, stripped)``. Does not truncate — callers reject bodies over 64 kB.
    """
    if not html:
        return "", []
    cleaned = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    cleaned = _drop_disallowed_signature_src(cleaned)
    cleaned = _mark_signature_urls(cleaned)
    return cleaned, signature_stripped_parts(html, cleaned)


def sanitize_html(html: str, *, max_bytes: int = _MAX_DEFAULT) -> str:
    """Return safe HTML. Empty input stays empty. Oversized bodies are truncated after sanitizing."""
    if not html:
        return ""
    cleaned = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    cleaned = _rewrite_remote_imgs(cleaned)
    raw = cleaned.encode("utf-8")
    if len(raw) <= max_bytes:
        return cleaned
    # cut on a character boundary
    cut = raw[:max_bytes].decode("utf-8", errors="ignore")
    return cut + "…"
