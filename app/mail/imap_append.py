"""IMAP APPEND helpers — Sent after SMTP, Drafts autosave (CLAUDE.md §5, GitHub #20 / #23)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.message import EmailMessage

import structlog
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from app.mail.folders import ListedFolder
from app.mail.imap import ImapServer
from app.mail.sent_folder import choose_sent_folder
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, connect, logout_quietly

log = structlog.get_logger(__name__)

SENT_FALLBACKS = ("Sent", "Odoslané", "Odoslane", "Sent Items")
DRAFTS_FALLBACKS = ("Drafts", "Koncepty", "Draft")


@dataclass(frozen=True)
class AppendedMessage:
    uid: int | None
    folder: str


def _as_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def read_personal_namespace(client: IMAPClient) -> tuple[str, str]:
    """RFC 2342 personal namespace as ``(prefix, delimiter)``. Empty prefix and ``/`` if missing."""
    try:
        raw = client.namespace()
    except (IMAPClientError, OSError):
        return "", "/"
    personal = raw[0] if isinstance(raw, tuple) and raw else None
    if not personal:
        return "", "/"
    first = personal[0]
    prefix = _as_text(first[0]) if first[0] is not None else ""
    delimiter = _as_text(first[1]) if len(first) > 1 and first[1] else "/"
    if prefix in {"None", "NIL"}:
        prefix = ""
    return prefix, delimiter or "/"


def _listed(client: IMAPClient) -> list[ListedFolder]:
    try:
        rows = client.list_folders()
    except IMAPClientError as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    listed: list[ListedFolder] = []
    for flags, delim, name in rows:
        label = name if isinstance(name, str) else _as_text(name)
        if isinstance(flags, (list, tuple, set, frozenset)):
            flag_set = frozenset(_as_text(flag) for flag in flags)
        else:
            flag_set = frozenset()
        listed.append(ListedFolder(label, _as_text(delim) if delim else None, flag_set))
    return listed


def ensure_sent_folder(client: IMAPClient, *, known: str | None) -> str:
    """Folder to APPEND into. Creates a mailbox only when none exists, using NAMESPACE."""
    listed = _listed(client)
    folder, create = choose_sent_folder(listed, known=known, prefix="", delimiter="/")
    # NAMESPACE is consulted only when nothing to reuse exists, so a missing NAMESPACE
    # command still lands in an existing \\Sent / Odoslané mailbox.
    if create:
        prefix, delimiter = read_personal_namespace(client)
        folder, create = choose_sent_folder(listed, known=known, prefix=prefix, delimiter=delimiter)
    if not create:
        return folder
    try:
        client.create_folder(folder)
    except IMAPClientError as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    try:
        client.subscribe_folder(folder)
    except IMAPClientError:
        log.warning("imap.sent_subscribe_failed", folder=folder)
    return folder


def _flag_set(flags: object) -> set[bytes]:
    out: set[bytes] = set()
    if not isinstance(flags, (list, tuple, set, frozenset)):
        return out
    for flag in flags:
        if isinstance(flag, bytes):
            out.add(flag.upper())
        elif isinstance(flag, str):
            out.add(flag.encode("ascii", errors="ignore").upper())
    return out


def resolve_special_folder(
    client: IMAPClient,
    *,
    special: bytes,
    fallbacks: tuple[str, ...],
) -> str:
    """Pick SPECIAL-USE folder, else a known Roundcube SK/EN name, else create the first fallback."""
    wanted = special.upper()
    try:
        listed = client.list_folders()
    except IMAPClientError as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    for flags, _delim, name in listed:
        if wanted in _flag_set(flags):
            return name if isinstance(name, str) else name.decode("utf-8", errors="replace")
    for candidate in fallbacks:
        for _flags, _delim, name in listed:
            label = name if isinstance(name, str) else name.decode("utf-8", errors="replace")
            if label.lower() == candidate.lower():
                return label
    target = fallbacks[0]
    try:
        client.create_folder(target)
    except IMAPClientError:
        pass
    return target


def append_rfc822(
    server: ImapServer,
    creds: Credentials,
    *,
    folder: str,
    message: EmailMessage | bytes,
    flags: tuple[str, ...] = (),
) -> int | None:
    """APPEND a message; returns UID when the server sends APPENDUID, else None."""
    raw = message.as_bytes() if isinstance(message, EmailMessage) else message
    client = connect(server, creds)
    try:
        response = client.append(folder, raw, flags=flags)
        # imapclient may return (uidvalidity, uid) via APPENDUID or None
        if isinstance(response, tuple) and len(response) == 2 and isinstance(response[1], int):
            return int(response[1])
        return None
    except SyncAuthError:
        raise
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    finally:
        logout_quietly(client)


def _append_uid(response: object) -> int | None:
    if isinstance(response, tuple) and len(response) == 2 and isinstance(response[1], int):
        return int(response[1])
    return None


def append_to_sent(
    server: ImapServer,
    creds: Credentials,
    message: EmailMessage,
    *,
    known_folder: str | None = None,
) -> AppendedMessage:
    """APPEND to the Sent folder sync already knows, else \\Sent / a known name, else CREATE.

    ``known_folder`` is ``folders_meta`` special-use ``sent`` (GitHub #23). A new mailbox is
    created only when none exists, with the server NAMESPACE prefix and delimiter.
    """
    client = connect(server, creds)
    try:
        folder = ensure_sent_folder(client, known=known_folder)
        response = client.append(folder, message.as_bytes(), flags=[r"\Seen"])
        return AppendedMessage(uid=_append_uid(response), folder=folder)
    except SyncAuthError:
        raise
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    finally:
        logout_quietly(client)


def save_draft_replace(
    server: ImapServer,
    creds: Credentials,
    message: EmailMessage,
    *,
    previous_uid: int | None,
) -> int | None:
    """APPEND a new \\Draft, then delete the previous UID (CLAUDE.md §5 autosave)."""
    client = connect(server, creds)
    try:
        folder = resolve_special_folder(client, special=b"\\Drafts", fallbacks=DRAFTS_FALLBACKS)
        response = client.append(folder, message.as_bytes(), flags=[r"\Draft"])
        new_uid: int | None = None
        if isinstance(response, tuple) and len(response) == 2 and isinstance(response[1], int):
            new_uid = int(response[1])
        if previous_uid is not None and previous_uid != new_uid:
            try:
                client.select_folder(folder)
                client.delete_messages([previous_uid])
                client.expunge()
            except IMAPClientError as exc:
                log.warning("imap.draft_delete_failed", error_type=type(exc).__name__)
        return new_uid
    except SyncAuthError:
        raise
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    finally:
        logout_quietly(client)


def delete_draft_uid(server: ImapServer, creds: Credentials, uid: int) -> None:
    client = connect(server, creds)
    try:
        folder = resolve_special_folder(client, special=b"\\Drafts", fallbacks=DRAFTS_FALLBACKS)
        client.select_folder(folder)
        client.delete_messages([uid])
        client.expunge()
    except SyncAuthError:
        raise
    except (OSError, IMAPClientError) as exc:
        raise SyncUnavailable(type(exc).__name__) from exc
    finally:
        logout_quietly(client)


async def append_to_sent_async(
    server: ImapServer,
    creds: Credentials,
    message: EmailMessage,
    *,
    known_folder: str | None = None,
) -> AppendedMessage:
    return await asyncio.to_thread(append_to_sent, server, creds, message, known_folder=known_folder)


async def save_draft_replace_async(
    server: ImapServer,
    creds: Credentials,
    message: EmailMessage,
    *,
    previous_uid: int | None,
) -> int | None:
    return await asyncio.to_thread(save_draft_replace, server, creds, message, previous_uid=previous_uid)


async def delete_draft_uid_async(server: ImapServer, creds: Credentials, uid: int) -> None:
    await asyncio.to_thread(delete_draft_uid, server, creds, uid)
