"""Lazy-fetch message bodies from IMAP into object storage (Phase 1d/1e).

Fetch uses BODY.PEEK[] only — never RFC822 — so opening a message does not set \\Seen on the server.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.models import Attachment, FolderMeta, Mailbox, Message
from app.mail.parse import has_file_attachments, parse_rfc822
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, connect, logout_quietly, server_of

# Never include RFC822: that fetch marks the message \\Seen on many servers.
_BODY_FETCH = ["BODY.PEEK[]"]


async def ensure_body(
    db: AsyncSession,
    settings: Settings,
    mailbox: Mailbox,
    message: Message,
    creds: Credentials,
) -> Message:
    """Fetch and store the body once; later opens reuse the stored copy."""
    if message.body_fetched_at is not None and message.raw_storage_key:
        return message
    folder = await db.get(FolderMeta, message.folder_id)
    if folder is None:
        return message

    def fetch() -> bytes:
        client = connect(server_of(mailbox, settings), creds)
        try:
            client.select_folder(folder.name, readonly=True)
            data = client.fetch([message.uid], _BODY_FETCH)
            item = data.get(message.uid) or {}
            raw = item.get(b"BODY[]") or item.get(b"BODY.PEEK[]") or b""
            if not isinstance(raw, (bytes, bytearray)):
                return b""
            return bytes(raw)
        finally:
            logout_quietly(client)

    try:
        raw = await asyncio.to_thread(fetch)
    except SyncAuthError:
        raise
    except Exception as exc:
        raise SyncUnavailable(str(exc)) from exc

    if not raw:
        message.body_fetched_at = datetime.now(UTC)
        message.body_text = message.body_text or ""
        return message

    key, _sha = storage.put_bytes(settings, raw, prefix=f"mail/{mailbox.id}/raw")
    parsed = parse_rfc822(raw, settings)
    message.raw_storage_key = key
    message.body_text = parsed.body_text
    message.body_html_sanitized = parsed.body_html_sanitized
    message.preview = parsed.preview
    message.auth_results = parsed.auth_results
    message.has_attachments = has_file_attachments(parsed)
    message.body_fetched_at = datetime.now(UTC)

    from app.mail.clamav import scan_bytes

    await db.execute(delete(Attachment).where(Attachment.message_id == message.id))
    for part in parsed.attachments:
        av = await scan_bytes(settings, part.payload)
        akey, digest = storage.put_bytes(settings, part.payload, prefix=f"mail/{mailbox.id}/att")
        db.add(
            Attachment(
                message_id=message.id,
                filename=part.filename,
                content_type=part.content_type,
                size=len(part.payload),
                content_id=part.content_id,
                is_inline=part.is_inline,
                storage_key=akey,
                sha256=digest,
                av_status=av,
            )
        )
    await db.flush()
    return message


async def load_attachments(db: AsyncSession, message_id: object) -> list[Attachment]:
    result = await db.execute(
        select(Attachment).where(Attachment.message_id == message_id).order_by(Attachment.filename)
    )
    return list(result.scalars())
