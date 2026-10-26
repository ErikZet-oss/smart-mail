"""Parse a raw RFC822 message into text/HTML parts and attachment payloads (Phase 1d)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email import message_from_bytes
from email.message import Message
from email.policy import default
from email.utils import parsedate_to_datetime

from app.mail.sanitize import sanitize_html

_PREVIEW_LEN = 200
_WS = re.compile(r"\s+")


@dataclass
class ParsedAttachment:
    filename: str
    content_type: str
    payload: bytes
    content_id: str | None
    is_inline: bool


@dataclass
class ParsedMessage:
    body_text: str | None
    body_html_sanitized: str | None
    preview: str | None
    attachments: list[ParsedAttachment] = field(default_factory=list)
    auth_results: dict[str, str] | None = None


def _decode_part(part: Message) -> bytes:
    try:
        raw = part.get_payload(decode=True)
    except Exception:
        return b""
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray):
        return bytes(raw)
    return b""


def _text_of(part: Message) -> str:
    data = _decode_part(part)
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _filename(part: Message) -> str:
    name = part.get_filename()
    if name:
        return str(name)[:255]
    subtype = (part.get_content_subtype() or "bin").replace("/", "-")
    return f"priloha.{subtype}"[:255]


def _preview_from(text: str | None, html: str | None) -> str | None:
    source = text or ""
    if not source and html:
        source = re.sub(r"<[^>]+>", " ", html)
    source = _WS.sub(" ", source).strip()
    if not source:
        return None
    return source[:_PREVIEW_LEN]


def _auth_results(msg: Message) -> dict[str, str] | None:
    raw = msg.get("Authentication-Results")
    if not raw:
        return None
    out: dict[str, str] = {}
    for key in ("spf", "dkim", "dmarc"):
        match = re.search(rf"\b{key}=(pass|fail|softfail|neutral|none|temperror|permerror)", str(raw), re.I)
        if match:
            out[key] = match.group(1).lower()
    return out or {"raw": str(raw)[:500]}


def parse_rfc822(raw: bytes) -> ParsedMessage:
    msg = message_from_bytes(raw, policy=default)
    text: str | None = None
    html: str | None = None
    attachments: list[ParsedAttachment] = []

    if msg.is_multipart():
        for part in msg.walk():
            if part.is_multipart():
                continue
            disposition = (part.get_content_disposition() or "").lower()
            ctype = part.get_content_type()
            cid = part.get("Content-ID")
            cid_clean = cid.strip("<>") if cid else None
            if disposition == "attachment" or (
                disposition == "inline" and ctype != "text/plain" and ctype != "text/html"
            ):
                payload = _decode_part(part)
                if payload:
                    attachments.append(
                        ParsedAttachment(
                            filename=_filename(part),
                            content_type=ctype,
                            payload=bytes(payload),
                            content_id=cid_clean,
                            is_inline=disposition == "inline" or cid_clean is not None,
                        )
                    )
                continue
            if ctype == "text/plain" and text is None:
                text = _text_of(part)
            elif ctype == "text/html" and html is None:
                html = _text_of(part)
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            html = _text_of(msg)
        else:
            text = _text_of(msg)

    sanitized = sanitize_html(html) if html else None
    return ParsedMessage(
        body_text=text,
        body_html_sanitized=sanitized,
        preview=_preview_from(text, sanitized),
        attachments=attachments,
        auth_results=_auth_results(msg),
    )


def parse_date_header(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError):
        return None
