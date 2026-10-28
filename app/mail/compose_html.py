"""Outgoing compose HTML (issue #28).

The editor may show a signature and a quoted message, but those blocks are not
trusted. Send always rebuilds the signature with ``render_signature`` and the
quote from the original message HTML (remote image URLs kept).
"""

from __future__ import annotations

import re

from app.core.config import Settings
from app.mail.sanitize import REMOTE_PLACEHOLDER, quote_span, sanitize_html, sanitize_quote_html, signature_span

_DISPLAY_IMG = re.compile(rf"{re.escape(REMOTE_PLACEHOLDER)}|/api/mail/image-proxy", re.IGNORECASE)

_FORWARD_NOTE = "---------- Preposlaná správa ----------"


def strip_protected(html: str) -> str:
    """Drop signature and quote blocks. Their inner HTML is never trusted."""
    current = html or ""
    for _ in range(4):
        signature = signature_span(current)
        if signature is not None:
            current = signature[0] + signature[2]
            continue
        quoted = quote_span(current)
        if quoted is not None:
            current = quoted[0] + quoted[2]
            continue
        break
    return current


def _without_display_images(html: str) -> str:
    """Drop reading-pane placeholders. An outgoing quote must not carry them."""

    def repl(match: re.Match[str]) -> str:
        if _DISPLAY_IMG.search(match.group(0)):
            return ""
        return match.group(0)

    return re.sub(r"<img\b[^>]*>", repl, html, flags=re.IGNORECASE)


def assemble_outgoing_html(
    *,
    user_html: str,
    quote_html: str | None,
    signature_html: str | None,
    mode: str,
    settings: Settings | None = None,
) -> str:
    """User text (sanitised) plus a server-built quote and signature."""
    user = sanitize_html(strip_protected(user_html), settings=settings).strip()
    parts: list[str] = []
    if user:
        parts.append(user)
    if quote_html:
        inner = _without_display_images(sanitize_quote_html(quote_html)).strip()
        if mode == "forward" and inner:
            inner = f"<p>{_FORWARD_NOTE}</p>{inner}"
        if inner:
            parts.append(f'<blockquote data-sm-quote="1">{inner}</blockquote>')
    if signature_html:
        parts.append(f'<div data-sm-signature="1">{signature_html}</div>')
    return "".join(parts)


def normalize_signature_html(html: str) -> str:
    """Compare a settings preview with the MIME signature (logo URL or CID)."""
    text = html.replace("/logo-smart.svg", "cid:logo@smartmail")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r">\s+<", "><", text)
    return text.strip()
