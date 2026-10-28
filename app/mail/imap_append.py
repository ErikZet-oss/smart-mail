"""IMAP APPEND helpers — Sent after SMTP, Drafts autosave (CLAUDE.md §5, GitHub #20)."""

from __future__ import annotations

import asyncio
from email.message import EmailMessage

import structlog
from imapclient import IMAPClient
from imapclient.exceptions import IMAPClientError

from app.mail.imap import ImapServer
from app.mail.sync import Credentials, SyncAuthError, SyncUnavailable, connect, logout_quietly

log = structlog.get_logger(__name__)

SENT_FALLBACKS = ("Sent", "Odoslané", "Odoslane", "Sent Items")
DRAFTS_FALLBACKS = ("Drafts", "Koncepty", "Draft")


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


def append_to_sent(server: ImapServer, creds: Credentials, message: EmailMessage) -> int | None:
    """APPEND to \\Sent (fallback Sent/Odoslané) with \\Seen. Never raises for folder create races."""
    client = connect(server, creds)
    try:
        folder = resolve_special_folder(client, special=b"\\Sent", fallbacks=SENT_FALLBACKS)
        response = client.append(folder, message.as_bytes(), flags=[r"\Seen"])
        if isinstance(response, tuple) and len(response) == 2 and isinstance(response[1], int):
            return int(response[1])
        return None
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


async def append_to_sent_async(server: ImapServer, creds: Credentials, message: EmailMessage) -> int | None:
    return await asyncio.to_thread(append_to_sent, server, creds, message)


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
