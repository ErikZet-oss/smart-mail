"""Parse a raw RFC822 message into text/HTML parts and attachment payloads (Phase 1d / pilot B9–B10).

B9: Content-Disposition: attachment is always an attachment even with Content-ID (Gmail).
    Parts are marked is_inline only when the HTML body references their Content-ID via cid:.
B10: Non-text parts without Content-Disposition are kept (Apple Mail / Outlook / multipart/related).
    A second text/html or text/plain that has name/filename is an attachment.
"""

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
_CID_REF = re.compile(r"cid:([^\"'\s>]+)", re.IGNORECASE)


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
    # Content-Type name= parameter (common when Content-Disposition is absent)
    param = part.get_param("name")
    if isinstance(param, str) and param.strip():
        return param.strip()[:255]
    if isinstance(param, tuple) and param:
        return str(param[-1]).strip()[:255]
    subtype = (part.get_content_subtype() or "bin").replace("/", "-")
    return f"priloha.{subtype}"[:255]


def _has_name(part: Message) -> bool:
    if part.get_filename():
        return True
    param = part.get_param("name")
    if isinstance(param, str) and param.strip():
        return True
    if isinstance(param, tuple) and any(str(p).strip() for p in param if p is not None):
        return True
    return False


def _cid_clean(part: Message) -> str | None:
    cid = part.get("Content-ID")
    if not cid:
        return None
    return str(cid).strip().strip("<>").strip() or None


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


def cids_referenced_in_html(html: str | None) -> set[str]:
    """Content-IDs referenced by cid: URLs in HTML (without angle brackets)."""
    if not html:
        return set()
    return {m.group(1).strip().strip("<>") for m in _CID_REF.finditer(html) if m.group(1).strip()}


def _part_bytes(part: Message) -> bytes:
    payload = _decode_part(part)
    if payload:
        return bytes(payload)
    if part.get_content_maintype() != "message":
        return b""
    # message/rfc822: payload is a nested Message (or list of one)
    inner = part.get_payload()
    if isinstance(inner, list) and inner:
        first = inner[0]
        if isinstance(first, Message):
            return first.as_bytes(policy=default)
    if isinstance(inner, Message):
        return inner.as_bytes(policy=default)
    if isinstance(inner, (bytes, bytearray)):
        return bytes(inner)
    if isinstance(inner, str):
        return inner.encode("utf-8", errors="replace")
    return b""


def _append_attachment(
    attachments: list[ParsedAttachment],
    part: Message,
    *,
    force_not_inline: bool = False,
) -> None:
    payload = _part_bytes(part)
    if not payload:
        return
    cid = _cid_clean(part)
    attachments.append(
        ParsedAttachment(
            filename=_filename(part),
            content_type=part.get_content_type() or "application/octet-stream",
            payload=payload,
            content_id=cid,
            # Provisional; finalized after HTML is known (B9).
            is_inline=False if force_not_inline else bool(cid),
        )
    )


def _iter_leaf_parts(part: Message) -> list[Message]:
    """Collect leaf MIME parts without descending into message/* (keeps .eml intact)."""
    out: list[Message] = []
    _collect_leaf_parts(part, out)
    return out


def _collect_leaf_parts(part: Message, out: list[Message]) -> None:
    """Append leaf MIME parts without descending into message/* (keeps .eml intact)."""
    if part.get_content_maintype() == "multipart":
        payload = part.get_payload()
        if isinstance(payload, list):
            for child in payload:
                if isinstance(child, Message):
                    _collect_leaf_parts(child, out)
        return
    # message/rfc822 (and other message/*) is one attachment — do not walk its children.
    out.append(part)


def parse_rfc822(raw: bytes) -> ParsedMessage:
    msg = message_from_bytes(raw, policy=default)
    text: str | None = None
    html: str | None = None
    attachments: list[ParsedAttachment] = []

    if msg.is_multipart():
        for part in _iter_leaf_parts(msg):
            disposition = (part.get_content_disposition() or "").lower()
            ctype = part.get_content_type()
            is_body_text = ctype in {"text/plain", "text/html"}

            # Entire nested message is always an attachment (B10 fixture: .eml).
            if part.get_content_maintype() == "message":
                _append_attachment(attachments, part, force_not_inline=True)
                continue

            # B9: attachment disposition is always an attachment (even with Content-ID).
            if disposition == "attachment":
                _append_attachment(attachments, part, force_not_inline=True)
                continue

            # Explicit inline non-text (related images, etc.)
            if disposition == "inline" and not is_body_text:
                _append_attachment(attachments, part)
                continue

            # Body text/html: first plain and first html become the body; named extras are attachments (B10).
            if ctype == "text/plain":
                if text is None and not _has_name(part):
                    text = _text_of(part)
                else:
                    _append_attachment(attachments, part, force_not_inline=True)
                continue
            if ctype == "text/html":
                if html is None and not _has_name(part):
                    html = _text_of(part)
                else:
                    _append_attachment(attachments, part, force_not_inline=True)
                continue

            # B10: non-text with no Content-Disposition (Apple Mail / Outlook / multipart/related).
            if not is_body_text:
                _append_attachment(attachments, part)
                continue
    else:
        ctype = msg.get_content_type()
        if ctype == "text/html":
            html = _text_of(msg)
        elif ctype == "text/plain":
            text = _text_of(msg)
        else:
            _append_attachment(attachments, msg, force_not_inline=True)

    sanitized = sanitize_html(html) if html else None
    referenced = cids_referenced_in_html(html) | cids_referenced_in_html(sanitized)
    for att in attachments:
        if att.content_id and att.content_id in referenced:
            # Only hide as inline when the HTML actually references this CID (Roundcube parity).
            att.is_inline = True
        else:
            att.is_inline = False

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
