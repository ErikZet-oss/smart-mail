"""Folder actions of the folder column (SCREENS_SPEC G3): Označiť všetko ako prečítané, Vyprázdniť, Zhustiť, Nový
podpriečinok, Premenovať, Vymazať. Blocking imapclient calls; the API runs them in a thread and syncs afterwards."""

from __future__ import annotations

import enum
import imaplib
import ssl
from collections.abc import Callable

from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from app.mail.imap import ImapServer
from app.mail.sync import Credentials, SyncUnavailable, connect, logout_quietly


class FolderActionRefused(Exception):
    pass


class FolderAction(enum.StrEnum):
    mark_read = "mark_read"
    empty = "empty"
    compact = "compact"
    create = "create"
    rename = "rename"
    delete = "delete"


def _mark_read(client: IMAPClient, folder: str) -> None:
    client.select_folder(folder)
    uids = client.search(["UNSEEN"])
    if uids:
        client.add_flags(uids, [b"\\Seen"], silent=True)


def _empty(client: IMAPClient, folder: str) -> None:
    client.select_folder(folder)
    uids = client.search("ALL")
    if uids:
        client.delete_messages(uids, silent=True)
        client.expunge()


def _compact(client: IMAPClient, folder: str) -> None:
    client.select_folder(folder)
    client.expunge()


def run_folder_action(
    server: ImapServer,
    creds: Credentials,
    action: FolderAction,
    folder: str,
    target: str | None = None,
    ssl_context: ssl.SSLContext | None = None,
) -> None:
    client = connect(server, creds, ssl_context)
    try:
        ops: dict[FolderAction, Callable[[], None]] = {
            FolderAction.mark_read: lambda: _mark_read(client, folder),
            FolderAction.empty: lambda: _empty(client, folder),
            FolderAction.compact: lambda: _compact(client, folder),
            FolderAction.create: lambda: _create(client, folder),
            FolderAction.rename: lambda: _rename(client, folder, target),
            FolderAction.delete: lambda: _delete(client, folder),
        }
        ops[action]()
    except (OSError, imaplib.IMAP4.abort) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    except IMAPClientError as exc:  # tagged NO / BAD: the server refused this action (e.g. the name exists)
        raise FolderActionRefused from exc
    finally:
        logout_quietly(client)


def _create(client: IMAPClient, folder: str) -> None:
    client.create_folder(folder)
    client.subscribe_folder(folder)


def _rename(client: IMAPClient, folder: str, target: str | None) -> None:
    if not target:
        raise ValueError("rename needs a target")
    client.rename_folder(folder, target)
    client.subscribe_folder(target)
    try:
        client.unsubscribe_folder(folder)
    except IMAPClientError:
        pass


def _delete(client: IMAPClient, folder: str) -> None:
    try:
        client.unsubscribe_folder(folder)
    except IMAPClientError:
        pass
    client.delete_folder(folder)
