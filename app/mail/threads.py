"""Assign messages to threads after envelope sync (CLAUDE.md §5, Phase 1d)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import Message, Thread
from app.mail.threading import thread_key_for

WINDOW = timedelta(days=30)


def _key_str(kind: str, value: str) -> str:
    return f"{kind}:{value}"


async def link_message(db: AsyncSession, message: Message) -> Thread:
    to_emails = [str(a.get("email") or "") for a in (message.to_addrs or [])]
    key = thread_key_for(
        message_id=message.message_id,
        in_reply_to=message.in_reply_to,
        references=message.references,
        subject=message.subject,
        from_email=message.from_email,
        to_emails=to_emails,
        sent_at=message.sent_at or message.received_at,
    )
    stored = _key_str(key.kind, key.value)
    when = message.received_at or message.sent_at or datetime.now(UTC)

    thread = await db.scalar(select(Thread).where(Thread.mailbox_id == message.mailbox_id, Thread.thread_key == stored))
    if thread is None and key.kind == "fallback":
        # join a recent fallback thread with the same key prefix… keys are exact; WINDOW checked on last_message_at
        pass
    if thread is not None and thread.last_message_at is not None and when - thread.last_message_at > WINDOW:
        # too old — start a new thread with a disambiguated key
        stored = f"{stored}:{when.date().isoformat()}"
        thread = None

    if thread is None:
        thread = Thread(
            mailbox_id=message.mailbox_id,
            thread_key=stored,
            subject=message.subject,
            last_message_at=when,
            message_count=0,
            unread_count=0,
        )
        db.add(thread)
        await db.flush()

    message.thread_id = thread.id
    await db.flush()
    await refresh_thread_counts(db, thread.id)
    return thread


async def link_unthreaded(db: AsyncSession, mailbox_id: uuid.UUID, *, limit: int = 5000) -> int:
    rows = list(
        (
            await db.execute(
                select(Message)
                .where(Message.mailbox_id == mailbox_id, Message.thread_id.is_(None))
                .order_by(Message.received_at.asc().nulls_last())
                .limit(limit)
            )
        ).scalars()
    )
    for message in rows:
        await link_message(db, message)
    return len(rows)


async def refresh_thread_counts(db: AsyncSession, thread_id: uuid.UUID) -> None:
    total = await db.scalar(select(func.count()).select_from(Message).where(Message.thread_id == thread_id)) or 0
    unread = (
        await db.scalar(
            select(func.count()).select_from(Message).where(Message.thread_id == thread_id, Message.seen.is_(False))
        )
        or 0
    )
    flagged = (
        await db.scalar(
            select(func.count()).select_from(Message).where(Message.thread_id == thread_id, Message.flagged.is_(True))
        )
        or 0
    )
    has_att = (
        await db.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.thread_id == thread_id, Message.has_attachments.is_(True))
        )
        or 0
    )
    last = await db.scalar(select(func.max(Message.received_at)).where(Message.thread_id == thread_id))
    subject = await db.scalar(
        select(Message.subject)
        .where(Message.thread_id == thread_id)
        .order_by(Message.received_at.desc().nulls_last())
        .limit(1)
    )
    await db.execute(
        update(Thread)
        .where(Thread.id == thread_id)
        .values(
            message_count=int(total),
            unread_count=int(unread),
            flagged=bool(flagged),
            has_attachments=bool(has_att),
            last_message_at=last,
            subject=subject,
        )
    )
