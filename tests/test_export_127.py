"""#127 folder / mailbox backup to ZIP: raw .eml equal to the server, \\Seen untouched, manifest, date filter,
rights (mailbox, private folders), one export per mailbox, 24 h link."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail import export
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _folder_id, _signed_in


def _raw(subject: str, body: str = "Telo správy") -> bytes:
    return (
        f"Message-ID: <{subject.lower().replace(' ', '-')}@test>\r\nFrom: Anna <anna@customer.test>\r\n"
        f"Subject: {subject}\r\nDate: Mon, 1 Jun 2026 10:00:00 +0200\r\n\r\n{body}\r\n"
    ).encode()


OLD = datetime(2025, 1, 15, 9, 30, tzinfo=UTC)
NEW = datetime(2026, 10, 1, 8, 5, tzinfo=UTC)


class FakeImap:
    """Folders → {uid: (raw, internaldate)}; records every SELECT and FETCH item list."""

    def __init__(self, folders: dict[str, dict[int, tuple[bytes, datetime]]]) -> None:
        self.folders = folders
        self.selected: list[tuple[str, bool]] = []
        self.fetch_items: list[list[str]] = []
        self.current = ""

    def select_folder(self, name: str, readonly: bool = False) -> dict[bytes, Any]:
        self.selected.append((name, readonly))
        self.current = name
        return {b"UIDVALIDITY": 77}

    def search(self, criteria: list[Any]) -> list[int]:
        msgs = self.folders[self.current]
        since = before = None
        for i, c in enumerate(criteria):
            if c == "SINCE":
                since = criteria[i + 1]
            if c == "BEFORE":
                before = criteria[i + 1]
        return [
            uid
            for uid, (_, when) in msgs.items()
            if (since is None or when.date() >= since) and (before is None or when.date() < before)
        ]

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, Any]]:
        self.fetch_items.append(list(items))
        msgs = self.folders[self.current]
        return {
            u: {b"BODY[]": msgs[u][0], b"INTERNALDATE": msgs[u][1], b"RFC822.SIZE": len(msgs[u][0])}
            for u in uids
            if u in msgs
        }

    def logout(self) -> None:
        pass


SERVER = {
    "INBOX": {1: (_raw("Dopyt M8"), NEW), 2: (_raw("Stará objednávka"), OLD)},
    "Nitra": {5: (_raw("Faktúra Nitra"), OLD)},
    "Trash": {},
}


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> FakeImap:
    fake = FakeImap({k: dict(v) for k, v in SERVER.items()})
    monkeypatch.setattr("app.mail.export.connect", lambda *_a, **_k: fake)
    monkeypatch.setattr("app.mail.export.logout_quietly", lambda *_a, **_k: None)
    return fake


def test_127_range_bounds_and_imap_criteria() -> None:
    today = date(2026, 10, 30)
    assert export.ExportRange("all").imap_criteria(today) == ["ALL"]
    assert export.ExportRange("older", months=6).imap_criteria(today) == ["BEFORE", date(2026, 4, 30)]
    assert export.ExportRange("older", months=8).bounds(date(2026, 10, 31)) == (None, date(2026, 2, 28))
    between = export.ExportRange("between", date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert between.imap_criteria(today) == ["SINCE", date(2026, 1, 1), "BEFORE", date(2026, 2, 1)]


def test_127_zip_names_are_safe() -> None:
    assert export.slug("Faktúra č. 2026/0123 – Fixtech!") == "faktura-c-2026-0123-fixtech"
    assert export.slug("") == "bez-predmetu"
    folder = FolderMeta(name="Dodávatelia/Fixtech", delimiter="/")
    assert export.folder_dir(folder) == "dodavatelia/fixtech"


async def _run(app: FastAPI, client: Client, db: AsyncSession, settings: Settings, body: dict[str, Any]) -> Any:
    r = await client.send_json("POST", "/api/mail/mailboxes/default/exports", body)
    assert r.status_code == 202, r.text
    export_id = r.json()["id"]
    state = await export.run_export(app.state.redis, db, settings, export_id, today=date(2026, 10, 30))
    assert state is not None
    return export_id, state


async def test_127_export_three_folders_raw_equal_seen_untouched_manifest(
    app: FastAPI,
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    fake_imap: FakeImap,
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    ids = [await _folder_id(db, mailbox, n) for n in ("INBOX", "Nitra", "Trash")]
    export_id, state = await _run(app, client, db, settings, {"folder_ids": ids})
    assert state.status == "ready" and state.done == 3

    # read-only SELECT and BODY.PEEK[] only — nothing can set \Seen
    assert all(readonly for _, readonly in fake_imap.selected)
    assert all(items == ["BODY.PEEK[]", "INTERNALDATE", "RFC822.SIZE"] for items in fake_imap.fetch_items)

    r = await client.get(f"/api/mail/exports/{export_id}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(r.content))
    names = archive.namelist()
    inbox = [n for n in names if n.startswith("inbox/")]
    assert sorted(inbox) == ["inbox/2025-01-15_0930_stara-objednavka_2.eml", "inbox/2026-10-01_0805_dopyt-m8_1.eml"]
    assert archive.read("inbox/2026-10-01_0805_dopyt-m8_1.eml") == SERVER["INBOX"][1][0]  # raw bytes as on server
    assert archive.read("nitra/2025-01-15_0930_faktura-nitra_5.eml") == SERVER["Nitra"][5][0]

    manifest = archive.read("manifest.csv").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(manifest), delimiter=";"))
    assert {(r["folder"], r["uid"]) for r in rows} == {("INBOX", "1"), ("INBOX", "2"), ("Nitra", "5")}
    row = next(r for r in rows if r["uid"] == "1")
    assert row["message_id"] == "<dopyt-m8@test>" and row["subject"] == "Dopyt M8"
    assert row["size"] == str(len(SERVER["INBOX"][1][0])) and len(row["sha256"]) == 64

    # the safe-delete step may use exactly these UIDs
    assert state.manifest[ids[0]] == {"uidvalidity": 77, "uids": [1, 2]}
    audit = {a.action: a.details for a in (await db.scalars(select(AuditLog))).all()}
    assert audit["mail.export_started"]["folders"] == ["INBOX", "Nitra", "Trash"]
    assert audit["mail.export_downloaded"]["messages"] == 3
    assert "Dopyt" not in str(audit)  # no mail content in the audit


async def test_127_older_than_filter(
    app: FastAPI,
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    fake_imap: FakeImap,
) -> None:
    await _signed_in(client, db, mail_server)
    _, state = await _run(app, client, db, settings, {"range": {"kind": "older", "months": 6}})
    assert state.done == 2  # only the two 2025 messages
    assert all(s.get("uids") != [1] for s in state.manifest.values())


async def test_127_include_children(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    db.add(FolderMeta(mailbox_id=mailbox.id, name="Nitra/2025", delimiter="/", selectable=True))
    nitra = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "Nitra"))
    assert nitra is not None
    nitra.delimiter = "/"
    await db.commit()
    body = {"folder_ids": [str(nitra.id)], "include_children": True}
    assert (await client.send_json("POST", "/api/mail/mailboxes/default/exports/estimate", body)).json()["folders"] == 2
    body["include_children"] = False
    assert (await client.send_json("POST", "/api/mail/mailboxes/default/exports/estimate", body)).json()["folders"] == 1


async def test_127_estimate_counts_synced_messages(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    inbox = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert inbox is not None
    for uid, when in ((1, NEW), (2, OLD)):
        db.add(Message(mailbox_id=mailbox.id, folder_id=inbox.id, uid=uid, size=1000, received_at=when))
    await db.commit()
    r = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/exports/estimate",
        {"folder_ids": [str(inbox.id)], "range": {"kind": "older", "months": 6}},
    )
    assert r.json() == {"folders": 1, "messages": 1, "bytes": 1000}
    bad = await client.send_json("POST", "/api/mail/mailboxes/default/exports/estimate", {"range": {"kind": "older"}})
    assert bad.status_code == 422


async def test_127_private_folder_of_someone_else_is_403(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    nitra = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "Nitra"))
    assert nitra is not None
    nitra.private, nitra.owner_person_id = True, None  # private, not this person's
    await db.commit()
    r = await client.send_json("POST", "/api/mail/mailboxes/default/exports/estimate", {"folder_ids": [str(nitra.id)]})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "folder_private"
    whole = await client.send_json("POST", "/api/mail/mailboxes/default/exports/estimate", {})
    assert whole.status_code == 200 and whole.json()["folders"] == 2  # the whole mailbox leaves it out


async def test_127_no_access_to_mailbox_is_404(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    from tests.conftest import make_personal
    from tests.test_mail_sync_1c import make_mailbox

    await _signed_in(client, db, mail_server)
    other = await make_mailbox(db, await make_personal(db, email="iny@smartsro.sk"))
    await db.commit()
    r = await client.send_json("POST", f"/api/mail/mailboxes/{other.id}/exports", {})
    assert r.status_code == 404


async def test_127_one_running_export_per_mailbox_and_owner_only(
    app: FastAPI, client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    first = await client.send_json("POST", "/api/mail/mailboxes/default/exports", {})
    assert first.status_code == 202
    second = await client.send_json("POST", "/api/mail/mailboxes/default/exports", {})
    assert second.status_code == 409 and second.json()["detail"]["code"] == "export_running"
    assert (await client.get(f"/api/mail/exports/{first.json()['id']}/download")).status_code == 409  # not ready
    assert (await client.get("/api/mail/exports/deadbeef")).status_code == 404


async def test_127_link_expires_after_24h_and_archive_is_deleted(
    app: FastAPI,
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    fake_imap: FakeImap,
) -> None:
    from app.mail import storage

    await _signed_in(client, db, mail_server)
    export_id, state = await _run(app, client, db, settings, {})
    assert storage.get_bytes(settings, state.storage_key) is not None
    # notification while the link is valid
    notes = (await client.get("/api/notifications")).json()["items"]
    ready = [n for n in notes if n["kind"] == "export_ready"]
    assert ready and ready[0]["params"]["export_id"] == export_id

    state.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await export.save_state(app.state.redis, state)
    assert (await client.get(f"/api/mail/exports/{export_id}/download")).status_code == 410
    assert not [n for n in (await client.get("/api/notifications")).json()["items"] if n["kind"] == "export_ready"]

    future = datetime.now(UTC).timestamp() + export.LINK_TTL_S + 10
    assert await export.delete_expired(app.state.redis, settings, now=future) == 1
    assert storage.get_bytes(settings, state.storage_key) is None


async def test_127_failed_imap_frees_the_lock(
    app: FastAPI,
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.mail.sync import SyncUnavailable

    def down(*_a: Any, **_k: Any) -> Any:
        raise SyncUnavailable("TimeoutError")

    monkeypatch.setattr("app.mail.export.connect", down)
    mailbox = await _signed_in(client, db, mail_server)
    _, state = await _run(app, client, db, settings, {})
    assert state.status == "failed" and state.error == "SyncUnavailable"
    assert not await app.state.redis.exists(export.lock_key(mailbox.id))
    assert (await client.send_json("POST", "/api/mail/mailboxes/default/exports", {})).status_code == 202


async def test_127_mailbox_model_has_no_new_columns() -> None:
    # job state lives in Redis (no data-model change, #127)
    assert "export" not in " ".join(c.name for c in Mailbox.__table__.columns)
