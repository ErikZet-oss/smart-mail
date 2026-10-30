"""AI catch-up (#135): the pipeline used to start only when a sync saw new mail, so mail whose classify or draft
call failed (e.g. before #131) waited for the next incoming message. A cron asks every 15 minutes whether a mailbox
has work left and enqueues the usual job (same `_job_id`, so never twice). Budget and shadow mode are unchanged —
the job itself checks them; a draft that failed 3× and a classification that failed 3× are not retried."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.classify import MAX_LLM_ATTEMPTS
from app.ai.models import Classification
from app.ai.pipeline import message_eligible_for_ai
from app.ai.reply import _candidates
from app.mail.models import FolderMeta, Mailbox, Message

SCAN_LIMIT = 500  # newest unclassified rows looked at per mailbox and run


def _attempts(cls: Classification | None) -> int:
    payload: dict[str, Any] = (cls.payload or {}) if cls is not None else {}
    try:
        return int(payload.get("llm_attempts") or 0)
    except (TypeError, ValueError):
        return MAX_LLM_ATTEMPTS


async def has_pending_classify(db: AsyncSession, mailbox: Mailbox) -> bool:
    """An eligible message without a finished classification that may still be retried (< 3 attempts)."""
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        return False
    rows = await db.execute(
        select(Message, FolderMeta, Classification)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .outerjoin(Classification, Classification.message_id == Message.id)
        .where(
            Message.mailbox_id == mailbox.id,
            Message.received_at.is_not(None),
            Message.received_at >= mailbox.ai_enabled_at,
            or_(Classification.id.is_(None), Classification.status != "done"),
        )
        .order_by(Message.received_at.desc())
        .limit(SCAN_LIMIT)
    )
    for message, folder, cls in rows.all():
        if not message_eligible_for_ai(mailbox, folder, message):
            continue
        if cls is not None and (cls.payload or {}).get("skip_reason"):
            continue  # given up for good (max attempts, …)
        if _attempts(cls) < MAX_LLM_ATTEMPTS:
            return True
    return False


async def has_pending_reply(db: AsyncSession, mailbox: Mailbox) -> bool:
    """A reply candidate without a suggestion whose draft has not failed 3× yet (same filter as the job)."""
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        return False
    return bool(await _candidates(db, mailbox))


async def mailboxes_with_work(db: AsyncSession) -> list[Mailbox]:
    out: list[Mailbox] = []
    for mailbox in (await db.scalars(select(Mailbox).where(Mailbox.ai_enabled.is_(True)))).all():
        if await has_pending_classify(db, mailbox) or await has_pending_reply(db, mailbox):
            out.append(mailbox)
    return out
