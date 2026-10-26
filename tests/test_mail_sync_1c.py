"""Phase 1c without a mail server: mailbox on first login, applying IMAP snapshots to the local copy (UIDVALIDITY,
expunge, flags, removed folders), the folder API's access and permission checks, and the live-server guard
(CLAUDE.md §5, §9; SCREENS_SPEC G3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Branch, Role
from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.folders import ListedFolder
from app.mail.models import FolderMeta, Mailbox, MailboxAccess, Message
from app.mail.sync import Envelope, FolderDelta, MailboxSnapshot, apply_snapshot, known_state, sync_mailbox
from tests.conftest import Client, FakeMailServer, make_branch, make_personal

PASSWORD = "Spravne-Heslo-1"
NOW = datetime(2026, 10, 26, 9, 0, tzinfo=UTC)


def env(uid: int, *flags: str, subject: str = "Objednávka") -> Envelope:
    return Envelope(
        uid=uid,
        message_id=f"<{uid}@example.test>",
        in_reply_to=None,
        references=None,
        subject=subject,
        from_name="Peter Hudec",
        from_email="hudec@kovotrnava.example",
        to=[{"name": None, "email": "pilot@smartmail.test"}],
        cc=[],
        sent_at=NOW,
        received_at=NOW,
        size=100,
        flags=list(flags),
        modseq=1,
    )


def snapshot(*deltas: FolderDelta, folders: tuple[str, ...] = ("INBOX", "Trash", "Nitra")) -> MailboxSnapshot:
    listed = [ListedFolder(n, "/", frozenset({"\\Trash"} if n == "Trash" else set())) for n in folders]
    special = {"INBOX": "inbox", "Trash": "trash"}
    return MailboxSnapshot(
        capabilities=["IMAP4REV1", "CONDSTORE"],
        listed=listed,
        subscribed=set(folders),
        special={k: v for k, v in special.items() if k in folders},
        quota_used_kb=930,
        quota_limit_kb=1000,
        folders=list(deltas),
    )


def delta(
    name: str,
    uidvalidity: int,
    uidnext: int,
    messages: int,
    unseen: int,
    *,
    reset: bool = False,
    new: list[Envelope] | None = None,
    flags: dict[int, tuple[list[str], int | None]] | None = None,
    present_uids: set[int] | None = None,
) -> FolderDelta:
    return FolderDelta(name, messages, unseen, uidvalidity, uidnext, 5, reset, new or [], flags or {}, present_uids)


async def make_mailbox(db: AsyncSession, account: Account, host: str = "localhost") -> Mailbox:
    mailbox = Mailbox(
        email=account.email, imap_host=host, imap_port=143, imap_security="none", credential_account_id=account.id
    )
    db.add(mailbox)
    await db.flush()
    db.add(MailboxAccess(account_id=account.id, mailbox_id=mailbox.id))
    await db.commit()
    return mailbox


async def uids(db: AsyncSession, mailbox: Mailbox, folder: str) -> list[int]:
    q = select(Message.uid).join(FolderMeta, FolderMeta.id == Message.folder_id)
    q = q.where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == folder).order_by(Message.uid)
    return list((await db.execute(q)).scalars())


# --- mailbox on login --------------------------------------------------------------------------------------------
async def test_1c_first_login_creates_the_own_mailbox_with_access(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    r = await client.get("/api/mail/mailboxes")
    assert r.status_code == 200
    assert [(m["email"], m["sync_state"]) for m in r.json()] == [(acc.email, "new")]
    mailbox = (await db.execute(select(Mailbox))).scalar_one()
    assert mailbox.credential_account_id == acc.id
    # a second login does not duplicate anything
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    assert await db.scalar(select(func.count()).select_from(MailboxAccess)) == 1


async def test_1c_branch_login_links_the_branch_to_its_mailbox(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    branch, acc = await make_branch(db, "Senica")
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    await db.refresh(branch)
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    assert (await db.get(Branch, branch.id)) is not None and branch.mailbox_id == mailbox.id


# --- applying snapshots --------------------------------------------------------------------------------------------
async def test_1c_sync_stores_envelopes_counts_and_quota(db: AsyncSession) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    snap = snapshot(delta("INBOX", 7, 4, 3, 1, new=[env(1, "\\Seen"), env(2), env(3, "\\Seen", "\\Flagged")]))
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await db.commit()
    assert await uids(db, mailbox, "INBOX") == [1, 2, 3]
    inbox = (await db.execute(select(FolderMeta).where(FolderMeta.name == "INBOX"))).scalar_one()
    assert (inbox.total, inbox.unread, inbox.uidvalidity, inbox.uidnext, inbox.special_use) == (3, 1, 7, 4, "inbox")
    flagged = (await db.execute(select(Message).where(Message.uid == 3))).scalar_one()
    assert flagged.seen and flagged.flagged and not flagged.answered
    assert (mailbox.quota_used_kb, mailbox.quota_limit_kb, mailbox.sync_state) == (930, 1000, "ok")


async def test_1c_sync_is_incremental_flags_and_expunges(db: AsyncSession) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 7, 4, 3, 3, new=[env(1), env(2), env(3)])), now=NOW)
    await db.commit()
    known = await known_state(db, mailbox.id)
    assert known["INBOX"].local_count == 3 and known["INBOX"].uidnext == 4
    # message 2 expunged, 1 read elsewhere (Roundcube), 4 arrived
    nxt = delta("INBOX", 7, 5, 3, 1, new=[env(4)], flags={1: (["\\Seen"], 6)}, present_uids={1, 3, 4})
    await apply_snapshot(db, mailbox, snapshot(nxt), now=NOW)
    await db.commit()
    assert await uids(db, mailbox, "INBOX") == [1, 3, 4]
    first = await db.execute(select(Message).where(Message.uid == 1).execution_options(populate_existing=True))
    assert first.scalar_one().seen


async def test_1c_uidvalidity_change_replaces_the_local_copy(db: AsyncSession) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 7, 3, 2, 0, new=[env(1), env(2)])), now=NOW)
    await db.commit()
    reset = delta("INBOX", 8, 2, 1, 0, reset=True, new=[env(1, subject="Nová")], present_uids={1})
    await apply_snapshot(db, mailbox, snapshot(reset), now=NOW)
    await db.commit()
    rows = (await db.execute(select(Message).execution_options(populate_existing=True))).scalars().all()
    assert [(m.uid, m.subject) for m in rows] == [(1, "Nová")]


async def test_1c_folder_removed_on_the_server_disappears_with_its_messages(db: AsyncSession) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    await apply_snapshot(db, mailbox, snapshot(delta("Nitra", 1, 2, 1, 1, new=[env(1)])), now=NOW)
    await db.commit()
    await apply_snapshot(db, mailbox, snapshot(folders=("INBOX", "Trash")), now=NOW)
    await db.commit()
    names = set((await db.execute(select(FolderMeta.name))).scalars())
    assert names == {"INBOX", "Trash"}
    assert await db.scalar(select(func.count()).select_from(Message)) == 0


# --- live-server guard ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("host", ["mail2.nameserver.sk", "imap.smartsro.sk"])
async def test_1c_sync_refuses_a_real_server_outside_prod(db: AsyncSession, settings: Settings, host: str) -> None:
    acc = await make_personal(db, mailbox_password_enc=encrypt(settings, PASSWORD))
    mailbox = await make_mailbox(db, acc, host=host)
    assert await sync_mailbox(db, mailbox, settings) == "error"
    assert mailbox.sync_error == "host_not_allowed"


def test_1c_sync_host_guard_settings() -> None:
    dev = Settings(app_env="dev")
    assert dev.sync_host_allowed("imap-test") and dev.sync_host_allowed("localhost")
    assert not dev.sync_host_allowed("mail2.nameserver.sk")
    assert Settings(app_env="dev", mail_sync_allow_real_server=True).sync_host_allowed("mail2.nameserver.sk")


async def test_1c_sync_without_stored_password_reports_no_credentials(db: AsyncSession, settings: Settings) -> None:
    mailbox = await make_mailbox(db, await make_personal(db))
    assert await sync_mailbox(db, mailbox, settings) == "error"
    assert mailbox.sync_error == "no_credentials"


# --- folder API checks ---------------------------------------------------------------------------------------------
async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer, role: Role = Role.sales) -> Mailbox:
    acc = await make_personal(db, role=role)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    await apply_snapshot(db, mailbox, snapshot(delta("INBOX", 1, 1, 0, 0), delta("Nitra", 1, 1, 0, 0)), now=NOW)
    await db.commit()
    return mailbox


async def _folder_id(db: AsyncSession, mailbox: Mailbox, name: str) -> str:
    q = select(FolderMeta.id).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == name)
    return str((await db.execute(q)).scalar_one())


async def test_g3_folder_column_lists_special_then_own_folders_with_quota(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    r = await client.get("/api/mail/mailboxes/default/folders")
    assert r.status_code == 200, r.text
    body = r.json()
    assert [(f["name"], f["special_use"]) for f in body["folders"]] == [
        ("INBOX", "inbox"),
        ("Trash", "trash"),
        ("Nitra", None),
    ]
    assert body["quota"] == {"used_kb": 930, "limit_kb": 1000, "percent": 93, "level": "danger"}
    assert body["mailbox"]["id"] == str(mailbox.id)


async def test_g3_other_logins_mailbox_is_not_visible(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    other = await make_mailbox(db, await make_personal(db, email="iny@smartsro.sk"))
    assert (await client.get(f"/api/mail/mailboxes/{other.id}/folders")).status_code == 404
    assert (await client.get(f"/api/mail/mailboxes/{uuid.uuid4()}/folders")).status_code == 404
    r = await client.send_json("POST", f"/api/mail/mailboxes/{other.id}/refresh")
    assert r.status_code == 404


async def test_g3_viewer_cannot_change_folders(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.viewer)
    nitra = await _folder_id(db, mailbox, "Nitra")
    r = await client.send_json("DELETE", f"/api/mail/mailboxes/default/folders/{nitra}")
    assert r.status_code == 403 and r.json()["detail"]["code"] == "read_only"
    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": "Nový"})
    assert r.status_code == 403


async def test_g3_special_folders_cannot_be_renamed_or_deleted(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    for name in ("INBOX", "Trash"):
        fid = await _folder_id(db, mailbox, name)
        r = await client.send_json("DELETE", f"/api/mail/mailboxes/default/folders/{fid}")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "special_folder"
        r = await client.send_json("PATCH", f"/api/mail/mailboxes/default/folders/{fid}", {"name": "X"})
        assert r.status_code == 409


async def test_g3_only_trash_and_junk_can_be_emptied(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    for name in ("INBOX", "Nitra"):
        fid = await _folder_id(db, mailbox, name)
        r = await client.send_json("POST", f"/api/mail/mailboxes/default/folders/{fid}/empty")
        assert r.status_code == 409 and r.json()["detail"]["code"] == "folder_not_emptyable"


@pytest.mark.parametrize(("name", "code"), [("a/b", "characters"), ("   ", "length"), ("INBOX", "reserved")])
async def test_g5_new_folder_name_is_validated(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, name: str, code: str
) -> None:
    await _signed_in(client, db, mail_server)
    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": name})
    assert r.status_code == 422 and r.json()["detail"]["code"] == f"folder_name_{code}"


async def test_g5_existing_folder_name_is_refused(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": "Nitra"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "folder_exists"
