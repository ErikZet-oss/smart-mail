"""IMAP flag / move / copy actions for messages (Phase 1d toolbar and bulk bar)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from app.mail.imap import ImapServer
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, connect, logout_quietly


class MsgAction(StrEnum):
    mark_seen = "mark_seen"
    mark_unseen = "mark_unseen"
    flag = "flag"
    unflag = "unflag"
    delete = "delete"  # move to Trash (or store \Deleted+\Expunge in Trash)
    junk = "junk"
    archive = "archive"
    move = "move"
    copy = "copy"


@dataclass(frozen=True)
class MsgTarget:
    folder: str
    uids: tuple[int, ...]


def run_msg_action(
    server: ImapServer,
    creds: Credentials,
    action: MsgAction,
    source: MsgTarget,
    *,
    dest_folder: str | None = None,
) -> None:
    if not source.uids:
        return
    client = connect(server, creds)
    try:
        _act(client, action, source, dest_folder)
    except SyncAuthError:
        raise
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    finally:
        logout_quietly(client)


def _act(client: IMAPClient, action: MsgAction, source: MsgTarget, dest: str | None) -> None:
    client.select_folder(source.folder)
    uids = list(source.uids)
    if action is MsgAction.mark_seen:
        client.add_flags(uids, [b"\\Seen"])
    elif action is MsgAction.mark_unseen:
        client.remove_flags(uids, [b"\\Seen"])
    elif action is MsgAction.flag:
        client.add_flags(uids, [b"\\Flagged"])
    elif action is MsgAction.unflag:
        client.remove_flags(uids, [b"\\Flagged"])
    elif action in (MsgAction.delete, MsgAction.junk, MsgAction.archive, MsgAction.move):
        if not dest:
            raise SyncUnavailable("dest_required")
        client.move(uids, dest)
    elif action is MsgAction.copy:
        if not dest:
            raise SyncUnavailable("dest_required")
        client.copy(uids, dest)
    else:
        raise SyncUnavailable("unknown_action")


async def run_msg_action_async(
    server: ImapServer,
    creds: Credentials,
    action: MsgAction,
    source: MsgTarget,
    *,
    dest_folder: str | None = None,
) -> None:
    await asyncio.to_thread(run_msg_action, server, creds, action, source, dest_folder=dest_folder)


def chunked(uids: Sequence[int], size: int = 200) -> list[list[int]]:
    return [list(uids[i : i + size]) for i in range(0, len(uids), size)]
