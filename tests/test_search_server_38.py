"""Issue #38: Telo / Celá správa also searched on the IMAP server, because bodies of unopened messages are not indexed
locally (Roundcube parity). The IMAP server is faked here; tests/integration/test_imap_body_search_38.py runs it
against Dovecot."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from imapclient.imapclient import _normalise_search_criteria
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.search as search_api
import app.mail.search as search_mod
from app.auth.models import Account
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.server_search import ServerSearchResult, search_criteria, server_terms
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import PASSWORD
from tests.test_search_1g import _folder, _msg, _signed_in


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
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, monkeypatch: pytest.MonkeyPatch
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
    )
    assert state == "ok"
    assert calls == [{"folders": ["INBOX"], "criteria": ["BODY", "paletový", "BODY", "nákup"]}]
    hits, total = await search_mod.search_messages(db, acc, q="paletový nákup", fields=["body"], server_uids=uids)
    assert total == 1 and hits[0].subject == "Faktúra"


async def test_38_full_message_uses_text_and_scope_limits_the_folders(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, monkeypatch: pytest.MonkeyPatch
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
    )
    assert calls == [{"folders": ["INBOX"], "criteria": ["TEXT", "DL-77"]}]

    # subject / sender fields never ask the server
    calls.clear()
    _, state = await search_mod.server_uid_hits(
        db, live, acc, q="DL-77", scope="all", fields=["subject"], folder_id=None, mailbox_ref="default", person_id=None
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
