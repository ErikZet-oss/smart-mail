"""Issue #38: Telo / Celá správa also searched on the IMAP server, because bodies of unopened messages are not indexed
locally (Roundcube parity). The IMAP server is faked here; tests/integration/test_imap_body_search_38.py runs it
against Dovecot."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from imapclient.imapclient import _normalise_search_criteria
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.search as search_api
import app.mail.search as search_mod
import app.mail.server_search as server_search_mod
from app.auth.models import Account
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.imap import ImapServer
from app.mail.server_search import ServerSearchResult, search_criteria, server_terms
from app.mail.sync import Credentials
from tests.conftest import TEST_REDIS_URL, Client, FakeMailServer
from tests.test_mail_sync_1c import PASSWORD
from tests.test_search_1g import _folder, _msg, _signed_in


@pytest.fixture
async def redis(migrated: str) -> AsyncIterator[Redis]:
    client = Redis.from_url(TEST_REDIS_URL)
    await client.flushdb()
    yield client
    await client.aclose()


async def _with_password(db: AsyncSession, settings: Settings, acc: Account) -> None:
    """The fake login does not store the mailbox password; the server search needs it (like the sync)."""
    stored = await db.get(Account, acc.id)
    assert stored is not None
    stored.mailbox_password_enc = encrypt(settings, PASSWORD)
    await db.commit()


def _fake_server(monkeypatch: pytest.MonkeyPatch, result: ServerSearchResult) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake(server: object, creds: object, folders: list[str], criteria: list[str], **kw: object) -> Any:
        calls.append({"folders": folders, "criteria": criteria})
        return result

    monkeypatch.setattr(search_mod, "search_folders_async", fake)
    return calls


async def test_38_body_of_an_unopened_message_is_found_on_the_server(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    redis: Redis,
) -> None:
    acc, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Faktúra", body=None)  # body never downloaded
    await _msg(db, mailbox, inbox, 2, subject="Iné", body=None)
    await db.commit()
    await _with_password(db, settings, acc)
    calls = _fake_server(monkeypatch, ServerSearchResult(uids={"INBOX": {1}}))
    live = settings.model_copy(update={"mail_sync_enabled": True})

    _, total = await search_mod.search_messages(db, acc, q="paletový", fields=["body"])
    assert total == 0  # the local index does not know the body

    uids, state = await search_mod.server_uid_hits(
        db,
        live,
        acc,
        q="paletový nákup",
        scope="all",
        fields=["body"],
        folder_id=None,
        mailbox_ref="default",
        person_id=None,
        redis=redis,
    )
    assert state == "ok"
    assert calls == [{"folders": ["INBOX"], "criteria": ["BODY", "paletový", "BODY", "nákup"]}]
    hits, total = await search_mod.search_messages(db, acc, q="paletový nákup", fields=["body"], server_uids=uids)
    assert total == 1 and hits[0].subject == "Faktúra"


async def test_38_full_message_uses_text_and_scope_limits_the_folders(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    redis: Redis,
) -> None:
    acc, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _folder(db, mailbox, "Nitra")
    await db.commit()
    await _with_password(db, settings, acc)
    calls = _fake_server(monkeypatch, ServerSearchResult(uids={"INBOX": set()}))
    live = settings.model_copy(update={"mail_sync_enabled": True})
    await search_mod.server_uid_hits(
        db,
        live,
        acc,
        q="DL-77",
        scope="current",
        fields=["full"],
        folder_id=inbox.id,
        mailbox_ref="default",
        person_id=None,
        redis=redis,
    )
    assert calls == [{"folders": ["INBOX"], "criteria": ["TEXT", "DL-77"]}]

    # subject / sender fields never ask the server
    calls.clear()
    _, state = await search_mod.server_uid_hits(
        db,
        live,
        acc,
        q="DL-77",
        scope="all",
        fields=["subject"],
        folder_id=None,
        mailbox_ref="default",
        person_id=None,
        redis=redis,
    )
    assert state is None and calls == []


@pytest.mark.parametrize(
    "query",
    ["x) OR (ALL", '"a" \\ {5}', "a\r\nA1 LOGOUT", "%*]", "ÚČTO)"],
)
def test_38_server_terms_cannot_change_the_imap_command(query: str) -> None:
    terms = server_terms(query)
    if not terms:
        return  # nothing usable is left: the server is not asked at all
    for wire in _normalise_search_criteria(search_criteria(terms, key="BODY"), charset="UTF-8"):
        raw = getattr(wire, "original", wire)
        assert not set(raw.decode()) & set('()"\\{}%*]\r\n'), (query, wire)


def test_38_server_terms_keep_words_and_addresses() -> None:
    assert server_terms("faktúra  DL-1d-77 novak@abcstav.example") == ["faktúra", "DL-1d-77", "novak@abcstav.example"]
    assert len(server_terms(" ".join(f"w{i}" for i in range(30)))) == 10


async def test_38_api_merges_server_hits_and_reports_a_timeout(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Neotvorená", body=None)
    await _msg(db, mailbox, inbox, 2, subject="Otvorená", body="paletový odber")
    await db.commit()

    async def found(*args: object, **kwargs: object) -> tuple[dict[uuid.UUID, set[int]], str]:
        return {inbox.id: {1}}, "ok"

    monkeypatch.setattr(search_api, "server_uid_hits", found)
    r = await client.get("/api/search", params={"q": "paletový", "fields": "body", "server": "true"})
    assert r.status_code == 200, r.text
    assert {m["subject"] for m in r.json()["messages"]} == {"Neotvorená", "Otvorená"}
    assert r.json()["server_search"] == "ok"

    async def slow(*args: object, **kwargs: object) -> tuple[dict[uuid.UUID, set[int]], str]:
        return {}, "timeout"

    monkeypatch.setattr(search_api, "server_uid_hits", slow)
    r = await client.get("/api/search", params={"q": "paletový", "fields": "body", "server": "true"})
    assert {m["subject"] for m in r.json()["messages"]} == {"Otvorená"}  # local hits still shown
    assert r.json()["server_search"] == "timeout"

    r = await client.get("/api/search", params={"q": "paletový", "fields": "body"})
    assert r.json()["server_search"] is None


# --- review #60: one IMAP session per mailbox, bounded thread ----------------------------------------------------
async def _body_search(
    db: AsyncSession, settings: Settings, acc: Account, redis: Redis
) -> tuple[dict[uuid.UUID, set[int]], str | None]:
    return await search_mod.server_uid_hits(
        db,
        settings.model_copy(update={"mail_sync_enabled": True}),
        acc,
        q="paletový",
        scope="all",
        fields=["body"],
        folder_id=None,
        mailbox_ref="default",
        person_id=None,
        redis=redis,
    )


async def test_38_two_parallel_server_searches_use_one_imap_session_the_second_is_busy(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    redis: Redis,
) -> None:
    acc, mailbox = await _signed_in(client, db, mail_server)
    await _folder(db, mailbox, "INBOX", special_use="inbox")
    await db.commit()
    await _with_password(db, settings, acc)
    sessions = 0

    async def slow(*args: object, **kwargs: object) -> ServerSearchResult:
        nonlocal sessions
        sessions += 1
        await asyncio.sleep(0.5)
        return ServerSearchResult(uids={"INBOX": {1}})

    monkeypatch.setattr(search_mod, "search_folders_async", slow)
    other = async_sessionmaker(db.bind, expire_on_commit=False)
    async with other() as db2:
        first, second = await asyncio.gather(
            _body_search(db, settings, acc, redis), _body_search(db2, settings, acc, redis)
        )
    assert sessions == 1
    assert sorted([first[1] or "", second[1] or ""]) == ["busy", "ok"]


async def test_38_the_lock_is_released_after_a_timeout(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    redis: Redis,
) -> None:
    acc, mailbox = await _signed_in(client, db, mail_server)
    await _folder(db, mailbox, "INBOX", special_use="inbox")
    await db.commit()
    await _with_password(db, settings, acc)
    _fake_server(monkeypatch, ServerSearchResult(state="timeout"))
    assert (await _body_search(db, settings, acc, redis))[1] == "timeout"
    _fake_server(monkeypatch, ServerSearchResult(uids={"INBOX": set()}))
    assert (await _body_search(db, settings, acc, redis))[1] == "ok"  # not "busy"


class _SlowClient:
    def __init__(self) -> None:
        self.selected: list[str] = []

    def select_folder(self, name: str, readonly: bool = False) -> None:
        self.selected.append(name)
        time.sleep(0.2)

    def search(self, criteria: list[str], charset: str | None = None) -> list[int]:
        return [1]


def test_38_search_stops_before_the_next_folder_once_the_deadline_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _SlowClient()
    monkeypatch.setattr(server_search_mod, "connect", lambda *a, **k: client)
    monkeypatch.setattr(server_search_mod, "logout_quietly", lambda c: None)
    result = server_search_mod.search_folders(
        ImapServer("localhost", 143, "none", 30),
        Credentials("a@smartmail.test", "x"),
        ["INBOX", "Nitra", "Senica"],
        ["BODY", "x"],
        deadline=time.monotonic() + 0.1,
    )
    assert client.selected == ["INBOX"]
    assert result.state == "partial" and result.uids == {"INBOX": {1}}


async def test_38_the_imap_socket_timeout_is_bounded_by_the_search_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake(server: ImapServer, creds: object, folders: list[str], criteria: list[str], **kw: object) -> Any:
        seen["timeout_s"] = server.timeout_s
        seen["deadline"] = kw.get("deadline")
        return ServerSearchResult()

    monkeypatch.setattr(server_search_mod, "search_folders", fake)
    await server_search_mod.search_folders_async(
        ImapServer("localhost", 143, "none", 120),
        Credentials("a@smartmail.test", "x"),
        ["INBOX"],
        ["BODY", "x"],
        timeout_s=15,
    )
    assert seen["timeout_s"] == 15
    assert isinstance(seen["deadline"], float)
