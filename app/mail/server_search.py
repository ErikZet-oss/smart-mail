"""Body search on the IMAP server (issue #38, Roundcube parity).

Sync stores envelopes only and bodies are fetched on open, so the local full-text index (ADR-009) knows the body of
opened messages only. For the fields Telo / Celá správa, `UID SEARCH CHARSET UTF-8 BODY|TEXT` runs on the folders in
scope and the UIDs are merged with the local hits. The local index stays primary (it folds accents; the server may
not). Terms are reduced to word characters and `@ . _ + -`, so no IMAP atom-special can change the command; 8-bit
terms go out as literals (imapclient).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import structlog
from imapclient.exceptions import IMAPClientError, LoginError

from app.mail.imap import ImapServer
from app.mail.sync import Credentials, SyncAuthError, connect, logout_quietly

log = structlog.get_logger(__name__)

SERVER_SEARCH_TIMEOUT_S = 15.0
MAX_TERMS = 10
MAX_TERM_LEN = 100
_UNSAFE = re.compile(r"[^\w@.+\-]", re.UNICODE)

ServerSearchState = Literal["ok", "partial", "timeout", "unavailable"]


def server_terms(q: str) -> list[str]:
    """Words of the query, safe as IMAP search strings (no `( ) " \\ { } % * ]`, no control characters)."""
    terms: list[str] = []
    for part in q.split():
        clean = _UNSAFE.sub("", part)[:MAX_TERM_LEN]
        if clean:
            terms.append(clean)
    return terms[:MAX_TERMS]


def search_criteria(terms: Iterable[str], *, key: Literal["BODY", "TEXT"]) -> list[str]:
    """`BODY a BODY b` = every word must occur (like the local search, which ANDs the words)."""
    out: list[str] = []
    for term in terms:
        out += [key, term]
    return out


@dataclass
class ServerSearchResult:
    uids: dict[str, set[int]] = field(default_factory=dict)  # folder name → UIDs
    state: ServerSearchState = "ok"


def search_folders(
    server: ImapServer,
    creds: Credentials,
    folders: list[str],
    criteria: list[str],
) -> ServerSearchResult:
    """Blocking: one login, `SELECT` read-only + `UID SEARCH` per folder. A folder that fails is skipped."""
    result = ServerSearchResult()
    client = connect(server, creds)
    try:
        for name in folders:
            try:
                client.select_folder(name, readonly=True)
                result.uids[name] = {int(uid) for uid in client.search(criteria, charset="UTF-8")}
            except IMAPClientError as exc:
                result.state = "partial"
                log.warning("mail.server_search_folder_failed", error=type(exc).__name__)
    finally:
        logout_quietly(client)
    return result


async def search_folders_async(
    server: ImapServer,
    creds: Credentials,
    folders: list[str],
    criteria: list[str],
    *,
    timeout_s: float = SERVER_SEARCH_TIMEOUT_S,
) -> ServerSearchResult:
    """Never raises: a slow or unreachable server gives `timeout` / `unavailable` and the local hits still show."""
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(search_folders, server, creds, folders, criteria), timeout=timeout_s
        )
    except TimeoutError:
        return ServerSearchResult(state="timeout")
    except (OSError, IMAPClientError, LoginError, SyncAuthError) as exc:
        log.warning("mail.server_search_failed", error=type(exc).__name__)
        return ServerSearchResult(state="unavailable")
