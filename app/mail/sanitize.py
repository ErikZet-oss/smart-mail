"""HTML sanitizer for message bodies (CLAUDE.md §5 / §14, SCREENS_SPEC W2c).

Remote http(s) images are replaced with a marker so the reading pane can show "Zobraziť obrázky"; cid: and data:
images stay (inline signature images, DECISIONS D22).

``data-sm-keep-src`` and ``data-cid`` are not accepted from message HTML. The server stamps
``data-sm-keep-src`` only after it has sanitized our own signature. A received message that
copies the attribute is blocked like any other remote image. A stamp we minted survives so
the reading pane can load that image through the signed proxy (CSP ``img-src 'self'``).
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Final

import nh3

from app.core.config import Settings, get_settings
from app.mail.image_proxy import signature_keep_ok, signature_keep_token

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

_COMMON_ATTRS: Final = {
    "*": {"class", "style", "title", "dir", "lang"},
    "a": {"href", "name", "target"},
    "td": {"colspan", "rowspan", "align", "valign", "width", "height"},
    "th": {"colspan", "rowspan", "align", "valign", "width", "height"},
    "col": {"span", "width"},
    "colgroup": {"span"},
    "table": {"width", "border", "cellpadding", "cellspacing", "align"},
}

# Received mail. ``data-sm-keep-src`` and ``data-cid`` are stripped — never taken from input.
_MESSAGE_ATTRS: Final = {**_COMMON_ATTRS, "img": {"src", "alt", "width", "height"}}
# Signatures. The keep-src stamp is added after nh3, not copied from the editor.
_SIGNATURE_ATTRS: Final = {**_COMMON_ATTRS, "img": {"src", "alt", "width", "height", "data-cid"}}

_URL_SCHEMES: Final = {"http", "https", "mailto", "cid", "data"}
_REMOTE_SRC = re.compile(
    r'(?P<pre><img\b[^>]*?\bsrc\s*=\s*)(?P<q>["\'])(?P<url>https?://[^"\']+)(?P=q)',
    re.IGNORECASE,
)


_IMG_TAG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_DANGER_TAGS = ("script", "iframe", "form", "input", "object", "embed", "base", "meta", "textarea", "button", "svg")
_KEEP_VAL = re.compile(
    r"""\sdata-sm-keep-src\s*=\s*(?P<q>["'])(?P<val>[^"']*)(?P=q)""",
    re.IGNORECASE,
)
_IMG_SRC = re.compile(r"""\bsrc\s*=\s*(?P<q>["'])(?P<url>[^"']*)(?P=q)""", re.IGNORECASE)
_REMOTE_ATTR = re.compile(
    r"""\sdata-remote-src\s*=\s*(?P<q>["'])(?P<url>https?://[^"']+)(?P=q)""",
    re.IGNORECASE,
)
_ALLOWED_SIG_SRC = re.compile(
    r"^(https://|cid:|data:image/(?:png|jpeg|gif|webp);|/api/settings/signature-images/|/api/mail/image-proxy\?|/logo-smart\.)",
    re.IGNORECASE,
)
_SIG_OPEN = re.compile(
    r"""<div\b[^>]*\bdata-sm-signature\s*=\s*(?P<q>["'])1(?P=q)[^>]*>""",
    re.IGNORECASE,
)
_QUOTE_OPEN = re.compile(
    r"""<blockquote\b[^>]*\bdata-sm-quote\s*=\s*(?P<q>["'])1(?P=q)[^>]*>""",
    re.IGNORECASE,
)


def _settings_of(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def _append_attr(tag: str, attr: str) -> str:
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + f" {attr}/>"
    return tag[:-1].rstrip() + f" {attr}>"


def _rewrite_remote_imgs(html: str) -> str:
    """Every remote image becomes a placeholder. The keep-src attribute is not a bypass."""

    def repl_src(match: re.Match[str]) -> str:
        q = match.group("q")
        url = match.group("url")
        return f"{match.group('pre')}{q}{REMOTE_PLACEHOLDER}{q} data-remote-src={q}{url}{q}"

    return _IMG_TAG.sub(lambda match: _REMOTE_SRC.sub(repl_src, match.group(0)), html)


def _trusted_signature_urls(html: str, settings: Settings) -> set[str]:
    """https URLs whose keep-src stamp was minted by this server."""
    found: set[str] = set()
    for tag in _IMG_TAG.findall(html):
        src = _IMG_SRC.search(tag)
        token = _KEEP_VAL.search(tag)
        if src is None or token is None:
            continue
        url = html_lib.unescape(src.group("url"))
        if signature_keep_ok(settings, url, token.group("val")):
            found.add(url)
    return found


def _restore_trusted_signature_imgs(html: str, urls: set[str], settings: Settings) -> str:
    """Put server-stamped signature images back (https src + a fresh stamp) after the remote rewrite."""
    if not urls:
        return html

    def repl(match: re.Match[str]) -> str:
        tag = match.group(0)
        remote = _REMOTE_ATTR.search(tag)
        if remote is None:
            return tag
        url = html_lib.unescape(remote.group("url"))
        if url not in urls:
            return tag
        src = _IMG_SRC.search(tag)
        if src is None:
            return tag
        q = src.group("q")
        safe = html_lib.escape(url, quote=True)
        token = signature_keep_token(settings, url)
        without_remote = _REMOTE_ATTR.sub("", tag)
        src_now = _IMG_SRC.search(without_remote)
        if src_now is None:
            return tag
        replaced = without_remote[: src_now.start()] + f"src={q}{safe}{q}" + without_remote[src_now.end() :]
        return _append_attr(replaced, f'data-sm-keep-src="{token}"')

    return _IMG_TAG.sub(repl, html)


def _mark_signature_urls(html: str, settings: Settings) -> str:
    """Stamp https signature images. Any keep-src value from the editor is discarded first."""

    def repl(match: re.Match[str]) -> str:
        tag = _KEEP_VAL.sub("", match.group(0))
        src = _IMG_SRC.search(tag)
        if src is None:
            return tag
        url = html_lib.unescape(src.group("url"))
        if not url.lower().startswith("https://"):
            return tag
        token = signature_keep_token(settings, url)
        return _append_attr(tag, f'data-sm-keep-src="{token}"')

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


def _tagged_span(html: str, opener: re.Pattern[str], open_tag: str, close_tag: str) -> tuple[str, str, str] | None:
    """Split one element, counting nested copies of the same tag."""
    opened = opener.search(html)
    if opened is None:
        return None
    depth = 1
    index = opened.end()
    lower = html.lower()
    open_l = open_tag.lower()
    close_l = close_tag.lower()
    while index < len(html) and depth:
        next_open = lower.find(open_l, index)
        next_close = lower.find(close_l, index)
        if next_close < 0:
            return None
        if next_open != -1 and next_open < next_close:
            depth += 1
            index = next_open + len(open_l)
            continue
        depth -= 1
        if depth == 0:
            inner = html[opened.end() : next_close]
            return html[: opened.start()], inner, html[next_close + len(close_tag) :]
        index = next_close + len(close_l)
    return None


def signature_span(html: str) -> tuple[str, str, str] | None:
    """Split ``<div data-sm-signature="1">…</div>``, including nested divs."""
    return _tagged_span(html, _SIG_OPEN, "<div", "</div>")


def quote_span(html: str) -> tuple[str, str, str] | None:
    """Split ``<blockquote data-sm-quote="1">…</blockquote>``, including nested quotes."""
    return _tagged_span(html, _QUOTE_OPEN, "<blockquote", "</blockquote>")


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


def sanitize_signature_html(html: str, settings: Settings | None = None) -> tuple[str, list[str]]:
    """nh3 for signatures (D22): tables, inline styles, img. https URLs stay. No remote-image placeholder.

    ``data-sm-keep-src`` from the input is dropped. The server adds its own stamp afterwards.
    Returns ``(html, stripped)``. Does not truncate — callers reject bodies over 64 kB.
    """
    if not html:
        return "", []
    resolved = _settings_of(settings)
    cleaned = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_SIGNATURE_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    cleaned = _drop_disallowed_signature_src(cleaned)
    cleaned = _mark_signature_urls(cleaned, resolved)
    return cleaned, signature_stripped_parts(html, cleaned)


def sanitize_quote_html(html: str, *, max_bytes: int = _MAX_DEFAULT) -> str:
    """Safe HTML for a reply or forward quote. Remote http(s) URLs stay, as in Roundcube.

    Display sanitizing (``sanitize_html``) replaces those URLs with a placeholder for our
    reading pane. The recipient needs the original URL. Scripts and event handlers are still removed.
    """
    if not html:
        return ""
    cleaned = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_MESSAGE_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    raw = cleaned.encode("utf-8")
    if len(raw) <= max_bytes:
        return cleaned
    cut = raw[:max_bytes].decode("utf-8", errors="ignore")
    return cut + "…"


def sanitize_html(html: str, *, max_bytes: int = _MAX_DEFAULT, settings: Settings | None = None) -> str:
    """Return safe HTML. Empty input stays empty. Oversized bodies are truncated after sanitizing.

    Remote images are placeholders. A keep-src value from the message is ignored. Images whose
    stamp this server created (our signature) keep their https URL and receive a fresh stamp.
    """
    if not html:
        return ""
    resolved = _settings_of(settings)
    trusted = _trusted_signature_urls(html, resolved)
    cleaned = nh3.clean(
        html,
        tags=_TAGS,
        attributes=_MESSAGE_ATTRS,
        url_schemes=_URL_SCHEMES,
        link_rel="noopener noreferrer",
    )
    cleaned = _rewrite_remote_imgs(cleaned)
    cleaned = _restore_trusted_signature_imgs(cleaned, trusted, resolved)
    raw = cleaned.encode("utf-8")
    if len(raw) <= max_bytes:
        return cleaned
    # cut on a character boundary
    cut = raw[:max_bytes].decode("utf-8", errors="ignore")
    return cut + "…"


def sanitize_compose_body(html: str, settings: Settings | None = None) -> str:
    """Message rules for the draft, signature rules for the ``data-sm-signature`` block.

    The signature block is sanitized on its own so https images there are stamped by the
    server. Images outside that block cannot opt out of remote-image blocking.
    """
    if not html:
        return ""
    span = signature_span(html)
    if span is None:
        before, inner, after = html, None, ""
    else:
        before, inner, after = span
    quoted = quote_span(before)
    if quoted is None:
        before_clean = sanitize_html(before, settings=settings)
    else:
        pre, quote_inner, mid = quoted
        before_clean = (
            sanitize_html(pre, settings=settings)
            + f'<blockquote data-sm-quote="1">{sanitize_html(quote_inner, settings=settings)}</blockquote>'
            + sanitize_html(mid, settings=settings)
        )
    if inner is None:
        return before_clean + sanitize_html(after, settings=settings)
    signature, _gone = sanitize_signature_html(inner, settings=settings)
    return before_clean + f'<div data-sm-signature="1">{signature}</div>' + sanitize_html(after, settings=settings)
