"""Re-scan attachments left as skipped/error when ClamAV was down (Phase 1h follow-up)."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.clamav import AvStatus, scan_bytes
from app.mail.compose_models import ComposeAttachment
from app.mail.models import Attachment

log = structlog.get_logger(__name__)

PENDING_STATUSES = ("skipped", "error")
DEFAULT_BATCH = 200

# Both models share storage_key / av_status; annotate explicitly so mypy does not widen to Base.
ScannableAttachment = Attachment | ComposeAttachment


async def rescan_pending_attachments(
    db: AsyncSession,
    settings: Settings,
    *,
    limit: int = DEFAULT_BATCH,
) -> dict[str, int]:
    """Re-scan up to `limit` Attachment + ComposeAttachment rows with skipped/error.

    When ClamAV still does not answer (`skipped`), the row is left unchanged so the next
    cron can try again. Updated rows become clean, infected, or error.
    """
    counts = {"checked": 0, "updated": 0, "clean": 0, "infected": 0, "error": 0, "still_pending": 0}
    remaining = max(0, limit)
    if remaining == 0:
        return counts

    inbound: list[Attachment] = list(
        (
            await db.execute(
                select(Attachment)
                .where(Attachment.av_status.in_(PENDING_STATUSES))
                .order_by(Attachment.updated_at.asc())
                .limit(remaining)
            )
        ).scalars()
    )
    remaining -= len(inbound)
    compose: list[ComposeAttachment] = []
    if remaining > 0:
        compose = list(
            (
                await db.execute(
                    select(ComposeAttachment)
                    .where(ComposeAttachment.av_status.in_(PENDING_STATUSES))
                    .order_by(ComposeAttachment.updated_at.asc())
                    .limit(remaining)
                )
            ).scalars()
        )

    rows: list[ScannableAttachment] = [*inbound, *compose]
    for row in rows:
        counts["checked"] += 1
        new_status = await _rescan_one(settings, row.storage_key)
        if new_status == "skipped":
            counts["still_pending"] += 1
            continue
        if new_status != row.av_status:
            row.av_status = new_status
            counts["updated"] += 1
        counts[new_status] = counts.get(new_status, 0) + 1

    if counts["updated"]:
        await db.commit()
    log.info("clamav.rescan", **counts)
    return counts


async def _rescan_one(settings: Settings, storage_key: str) -> AvStatus:
    data = storage.get_bytes(settings, storage_key)
    if data is None:
        return "error"
    return await scan_bytes(settings, data)


# Keep a typing-friendly alias for tests that assert on the return shape.
RescanCounts = dict[str, Any]
