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
    "img": {"src", "alt", "width", "height"},
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


def _rewrite_remote_imgs(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        q = match.group("q")
        url = match.group("url")
        return f"{match.group('pre')}{q}{REMOTE_PLACEHOLDER}{q} data-remote-src={q}{url}{q}"

    return _REMOTE_SRC.sub(repl, html)


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
