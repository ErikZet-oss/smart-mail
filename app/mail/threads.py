"""Assign messages to threads after envelope sync (CLAUDE.md §5, Phase 1d)."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.mail.models import Message, Thread
from app.mail.threading import thread_key_for

log = structlog.get_logger(__name__)

WINDOW = timedelta(days=30)


# threads.thread_key is varchar(80). A Message-ID may be up to 998 characters (bulk senders use long ones), and a
# thread older than WINDOW gets an ":YYYY-MM-DD" suffix (11 characters). Long values are stored as a stable hash,
# so a reply with the same long id still finds the same thread: "msgid:" (6) + 48 + 11 <= 80.
MAX_KEY_VALUE = 48


def _key_str(kind: str, value: str) -> str:
    if len(value) > MAX_KEY_VALUE:
        value = "h" + hashlib.sha256(value.encode()).hexdigest()[:40]
    return f"{kind}:{value}"


async def _thread_for(db: AsyncSession, mailbox_id: uuid.UUID, base: str, when: datetime) -> Thread | None:
    """The newest thread of this key (plain or with a window suffix) whose last message is within WINDOW."""
    candidates = (
        await db.execute(
            select(Thread)
            .where(
                Thread.mailbox_id == mailbox_id,
                (Thread.thread_key == base) | Thread.thread_key.startswith(f"{base}:", autoescape=True),
            )
            .order_by(Thread.last_message_at.desc().nulls_last())
        )
    ).scalars()
    for thread in candidates:
        if thread.last_message_at is None or abs(when - thread.last_message_at) <= WINDOW:
            return thread
    return None


async def link_message(db: AsyncSession, message: Message) -> Thread:
    stored = stored_key(message)
    when = message.received_at or message.sent_at or datetime.now(UTC)

    thread = await _thread_for(db, message.mailbox_id, stored, when)
    if thread is None:
        # No thread within WINDOW. The plain key is used first; later windows get a ":YYYY-MM-DD" suffix. Several
        # messages of the same day share that suffixed thread (pilot: carrier notifications with one subject).
        base_taken = await db.scalar(
            select(Thread.id).where(Thread.mailbox_id == message.mailbox_id, Thread.thread_key == stored)
        )
        if base_taken is not None:
            stored = f"{stored}:{when.date().isoformat()}"
            thread = await db.scalar(
                select(Thread).where(Thread.mailbox_id == message.mailbox_id, Thread.thread_key == stored)
            )

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


# Messages threaded per statement batch; one failing batch falls back to per-message SAVEPOINTs.
LINK_CHUNK = 500
_DAY_SUFFIX = re.compile(r":\d{4}-\d{2}-\d{2}$")


def stored_key(message: Message) -> str:
    """The thread key of a message without the window suffix (shared by `link_message` and the batch path)."""
    key = thread_key_for(
        message_id=message.message_id,
        in_reply_to=message.in_reply_to,
        references=message.references,
        subject=message.subject,
        from_email=message.from_email,
        to_emails=[str(a.get("email") or "") for a in (message.to_addrs or [])],
        sent_at=message.sent_at or message.received_at,
    )
    return _key_str(key.kind, key.value)


@dataclass
class _KnownThread:
    id: uuid.UUID
    last_message_at: datetime | None


class _ThreadIndex:
    """All threads of a mailbox in memory, so a first sync of 25,000 messages needs no query per message (#41)."""

    def __init__(self) -> None:
        self.by_key: dict[str, _KnownThread] = {}
        self.by_base: dict[str, list[str]] = {}

    def add(self, key: str, known: _KnownThread) -> None:
        self.by_key[key] = known
        base = _DAY_SUFFIX.sub("", key)
        self.by_base.setdefault(base, []).append(key)
        if base != key:
            self.by_base.setdefault(key, [])

    def within_window(self, base: str, when: datetime) -> tuple[str, _KnownThread] | None:
        keys = self.by_base.get(base, [])
        candidates = sorted(
            ((k, self.by_key[k]) for k in keys),
            key=lambda kv: kv[1].last_message_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        for key, known in candidates:
            if known.last_message_at is None or abs(when - known.last_message_at) <= WINDOW:
                return key, known
        return None


async def _thread_index(db: AsyncSession, mailbox_id: uuid.UUID) -> _ThreadIndex:
    index = _ThreadIndex()
    rows = await db.execute(
        select(Thread.id, Thread.thread_key, Thread.last_message_at).where(Thread.mailbox_id == mailbox_id)
    )
    for thread_id, key, last in rows.all():
        index.add(key, _KnownThread(thread_id, last))
    return index


async def _link_batch(db: AsyncSession, index: _ThreadIndex, messages: list[Message]) -> None:
    """Same rules as `link_message`, for many messages with a handful of statements."""
    new_threads: list[dict[str, object]] = []
    links: list[tuple[uuid.UUID, uuid.UUID]] = []
    for message in messages:
        stored = stored_key(message)
        when = message.received_at or message.sent_at or datetime.now(UTC)
        found = index.within_window(stored, when)
        if found is None and stored in index.by_key:
            stored = f"{stored}:{when.date().isoformat()}"
            if stored in index.by_key:
                found = (stored, index.by_key[stored])
        if found is None:
            known = _KnownThread(uuid.uuid4(), when)
            index.add(stored, known)
            new_threads.append(
                {
                    "id": known.id,
                    "mailbox_id": message.mailbox_id,
                    "thread_key": stored,
                    "subject": message.subject,
                    "last_message_at": when,
                    "message_count": 0,
                    "unread_count": 0,
                }
            )
        else:
            known = found[1]
            if known.last_message_at is None or when > known.last_message_at:
                known.last_message_at = when
        links.append((message.id, known.id))
    for start in range(0, len(new_threads), LINK_CHUNK):
        await db.execute(insert(Thread).values(new_threads[start : start + LINK_CHUNK]))
    await db.execute(
        text(
            "UPDATE messages SET thread_id = v.tid, updated_at = now() "
            "FROM unnest(CAST(:mids AS uuid[]), CAST(:tids AS uuid[])) AS v(mid, tid) WHERE messages.id = v.mid"
        ),
        {"mids": [m for m, _ in links], "tids": [t for _, t in links]},
    )
    await refresh_many_thread_counts(db, {t for _, t in links})
    for message, (_, thread_id) in zip(messages, links, strict=True):
        set_committed_value(message, "thread_id", thread_id)  # keep the session's copies in step with the UPDATE


async def refresh_many_thread_counts(db: AsyncSession, thread_ids: set[uuid.UUID]) -> None:
    """`refresh_thread_counts` for many threads in one statement."""
    if not thread_ids:
        return
    await db.execute(
        text(
            "UPDATE threads SET message_count = s.total, unread_count = s.unread, flagged = s.flagged, "
            "has_attachments = s.has_att, last_message_at = s.last, subject = s.subject, updated_at = now() "
            "FROM (SELECT thread_id, count(*) AS total, count(*) FILTER (WHERE NOT seen) AS unread, "
            "bool_or(flagged) AS flagged, bool_or(has_attachments) AS has_att, max(received_at) AS last, "
            "(array_agg(subject ORDER BY received_at DESC NULLS LAST))[1] AS subject "
            "FROM messages WHERE thread_id = ANY(CAST(:ids AS uuid[])) GROUP BY thread_id) AS s "
            "WHERE threads.id = s.thread_id"
        ),
        {"ids": list(thread_ids)},
    )


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
    index = await _thread_index(db, mailbox_id)
    linked = 0
    for start in range(0, len(rows), LINK_CHUNK):
        chunk = rows[start : start + LINK_CHUNK]
        refs = [(m, hashlib.sha256((m.message_id or str(m.id)).encode()).hexdigest()[:12]) for m in chunk]
        try:
            async with db.begin_nested():
                await _link_batch(db, index, chunk)
            linked += len(chunk)
            continue
        except Exception as exc:
            log.warning("mail.thread_batch_failed", messages=len(chunk), error=type(exc).__name__)
        index = await _thread_index(db, mailbox_id)  # the rolled-back batch may have added threads to the index
        # One bad message must not roll back the folder (#41): retry this batch one message per SAVEPOINT; a failure
        # leaves that message unthreaded (still listed in Zoznam mode) and the rest continue.
        for message, ref in refs:
            try:
                async with db.begin_nested():
                    await link_message(db, message)
                linked += 1
            except Exception as exc:
                log.warning("mail.thread_link_failed", message_ref=ref, error=type(exc).__name__)
        index = await _thread_index(db, mailbox_id)
    return linked


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
