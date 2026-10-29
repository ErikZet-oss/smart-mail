"""Re-parse stored raw messages after attachment/inline classification fixes (pilot #18 B9/B10)."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.clamav import scan_bytes
from app.mail.models import Attachment, Message
from app.mail.parse import has_file_attachments, parse_rfc822

log = structlog.get_logger(__name__)


async def reparse_messages_with_attachments(
    db: AsyncSession,
    settings: Settings,
    *,
    limit: int = 200,
) -> dict[str, int]:
    """Re-run parse_rfc822 on messages that claim attachments and have stored raw MIME."""
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.has_attachments.is_(True), Message.raw_storage_key.is_not(None))
                .order_by(Message.received_at.desc().nulls_last())
                .limit(limit)
            )
        ).scalars()
    )
    updated = 0
    skipped = 0
    errors = 0
    for message in rows:
        key = message.raw_storage_key
        if not key:
            skipped += 1
            continue
        raw = storage.get_bytes(settings, key)
        if not raw:
            skipped += 1
            continue
        try:
            parsed = parse_rfc822(raw, settings)
        except Exception as exc:
            log.warning("mail.reparse_failed", message_id=str(message.id), error=type(exc).__name__)
            errors += 1
            continue
        message.body_text = parsed.body_text
        message.body_html_sanitized = parsed.body_html_sanitized
        message.preview = parsed.preview
        message.auth_results = parsed.auth_results
        message.has_attachments = has_file_attachments(parsed)
        message.body_fetched_at = message.body_fetched_at or datetime.now(UTC)
        await db.execute(delete(Attachment).where(Attachment.message_id == message.id))
        mailbox_id = message.mailbox_id
        for part in parsed.attachments:
            av = await scan_bytes(settings, part.payload)
            akey, digest = storage.put_bytes(settings, part.payload, prefix=f"mail/{mailbox_id}/att")
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
        updated += 1
    if updated or errors:
        await db.commit()
    return {"updated": updated, "skipped": skipped, "errors": errors, "seen": len(rows)}
