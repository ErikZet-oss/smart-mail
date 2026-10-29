"""One-off paperclip backfill for mailboxes synced before #52: `UID FETCH … (BODYSTRUCTURE)` for messages that were
never opened, per folder, in throttled batches. Runs once per mailbox (Redis marker, no schema change) and under the
sync lock of the mailbox, so it never adds a parallel IMAP session to the sync, IDLE and Roundcube.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import structlog
from imapclient.exceptions import IMAPClientError
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.bodystructure import has_file_attachments_structure
from app.mail.imap import ImapServer
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import DELETE_CHUNK, LOCK_TIMEOUT_S, Credentials, connect, credentials_for, logout_quietly, server_of

log = structlog.get_logger(__name__)

BATCH = 500
PAUSE_S = 0.5  # between batches: the backfill must not compete with the sync or Roundcube


def done_key(mailbox_id: uuid.UUID) -> str:
    return f"smartmail:attachment-backfill:v1:{mailbox_id}"


def fetch_flags(
    server: ImapServer, creds: Credentials, folders: dict[str, list[int]], *, pause_s: float = PAUSE_S
) -> dict[str, set[int]]:
    """Blocking: folder → UIDs whose BODYSTRUCTURE has a file attachment."""
    found: dict[str, set[int]] = {}
    client = connect(server, creds)
    try:
        for name, uids in folders.items():
            client.select_folder(name, readonly=True)
            hits: set[int] = set()
            for start in range(0, len(uids), BATCH):
                data: dict[int, dict[bytes, Any]] = client.fetch(uids[start : start + BATCH], ["BODYSTRUCTURE"])
                hits |= {
                    int(uid) for uid, item in data.items() if has_file_attachments_structure(item.get(b"BODYSTRUCTURE"))
                }
                time.sleep(pause_s)
            found[name] = hits
    finally:
        logout_quietly(client)
    return found


async def backfill_mailbox(
    db: AsyncSession, redis: Redis, mailbox: Mailbox, settings: Settings, *, pause_s: float = PAUSE_S
) -> int | None:
    """Sets `has_attachments` on unopened messages from BODYSTRUCTURE. Returns the number of messages flagged, or None
    when skipped (already done, no password, sync busy)."""
    if await redis.exists(done_key(mailbox.id)):
        return None
    creds = await credentials_for(db, mailbox, settings)
    if creds is None or not settings.sync_host_allowed(mailbox.imap_host):
        return None
    rows = await db.execute(
        select(FolderMeta.name, Message.uid)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .where(
            Message.mailbox_id == mailbox.id,
            Message.body_fetched_at.is_(None),  # opened messages already have the authoritative flag
            Message.has_attachments.is_(False),
        )
    )
    folders: dict[str, list[int]] = {}
    for name, uid in rows.all():
        folders.setdefault(name, []).append(int(uid))
    lock = redis.lock(f"smartmail:mail-sync:{mailbox.id}", timeout=LOCK_TIMEOUT_S, blocking_timeout=1)
    if not await lock.acquire():
        return None  # the sync is busy; the next run tries again
    try:
        found = await asyncio.to_thread(fetch_flags, server_of(mailbox, settings), creds, folders, pause_s=pause_s)
    except (OSError, IMAPClientError) as exc:
        log.warning("mail.attachment_backfill_failed", mailbox_id=str(mailbox.id), error=type(exc).__name__)
        return None
    finally:
        try:
            await lock.release()
        except Exception as exc:  # expired meanwhile
            log.warning("mail.attachment_backfill_lock_release_failed", error=type(exc).__name__)

    from app.mail.threads import refresh_many_thread_counts

    flagged = 0
    folder_ids = dict(
        (await db.execute(select(FolderMeta.name, FolderMeta.id).where(FolderMeta.mailbox_id == mailbox.id))).all()
    )
    threads: set[uuid.UUID] = set()
    for name, uids in found.items():
        if not uids or name not in folder_ids:
            continue
        ordered = sorted(uids)
        for start in range(0, len(ordered), DELETE_CHUNK):  # bind-parameter budget, as in apply_snapshot (#39)
            result = await db.execute(
                update(Message)
                .where(
                    Message.folder_id == folder_ids[name],
                    Message.uid.in_(ordered[start : start + DELETE_CHUNK]),
                    Message.body_fetched_at.is_(None),
                )
                .values(has_attachments=True)
                .returning(Message.id, Message.thread_id)
            )
            for _, thread_id in result.all():
                flagged += 1
                if thread_id is not None:
                    threads.add(thread_id)
    await refresh_many_thread_counts(db, threads)
    await db.commit()
    await redis.set(done_key(mailbox.id), "1")
    log.info("mail.attachment_backfill_done", mailbox_id=str(mailbox.id), flagged=flagged)
    return flagged
