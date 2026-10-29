"""Apply a toolbar action to the local copy right after the IMAP command succeeded (#89).

The list then shows the result at once; the scheduled sync later brings the moved messages into the destination
folder with their new UIDs and corrects anything we could not know (server-side filters, other clients).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.actions import MsgAction
from app.mail.models import FolderMeta, Message
from app.mail.threads import refresh_many_thread_counts

REMOVING = frozenset({MsgAction.delete, MsgAction.junk, MsgAction.archive, MsgAction.move, MsgAction.expunge})
_FLAG = {
    MsgAction.mark_seen: ("\\Seen", True),
    MsgAction.mark_unseen: ("\\Seen", False),
    MsgAction.flag: ("\\Flagged", True),
    MsgAction.unflag: ("\\Flagged", False),
}


def _set_flag(message: Message, flag: str, on: bool) -> None:
    current = [str(item) for item in (message.flags or []) if str(item).casefold() != flag.casefold()]
    if on:
        current.append(flag)
    message.flags = sorted(current)
    if flag == "\\Seen":
        message.seen = on
    else:
        message.flagged = on


async def apply_action_locally(
    db: AsyncSession,
    action: MsgAction,
    folder: FolderMeta,
    messages: Sequence[Message],
    *,
    dest: FolderMeta | None = None,
) -> None:
    """Mirror `action` on `messages` (all in `folder`) in the DB; the caller commits."""
    thread_ids: set[uuid.UUID] = {m.thread_id for m in messages if m.thread_id is not None}
    if action in REMOVING:
        unread = sum(1 for m in messages if not m.seen)
        await db.execute(delete(Message).where(Message.id.in_([m.id for m in messages])))
        folder.total = max(0, (folder.total or 0) - len(messages))
        folder.unread = max(0, (folder.unread or 0) - unread)
        if dest is not None:
            dest.total = (dest.total or 0) + len(messages)
            dest.unread = (dest.unread or 0) + unread
    elif action is MsgAction.copy and dest is not None:
        # The source keeps its rows; the destination gets the copies (new UIDs) on the scheduled sync.
        dest.total = (dest.total or 0) + len(messages)
        dest.unread = (dest.unread or 0) + sum(1 for m in messages if not m.seen)
    elif action in _FLAG:
        flag, on = _FLAG[action]
        changed = [m for m in messages if (m.seen if flag == "\\Seen" else m.flagged) != on]
        for m in messages:
            _set_flag(m, flag, on)
        if flag == "\\Seen":
            delta = -len(changed) if on else len(changed)
            folder.unread = max(0, (folder.unread or 0) + delta)
    await db.flush()
    await refresh_many_thread_counts(db, thread_ids)
