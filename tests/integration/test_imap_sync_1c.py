"""Phase 1c against the local test IMAP server (docker compose `imap-test`, Dovecot with QUOTA + ManageSieve, seeded by
`tools/seed_test_imap.py` with fictional mail only). Login → own mailbox → folder column, incremental sync,
flags/expunge, folder actions, quota above 90 %, password changed on the server.

Runs when TEST_IMAP_HOST is set (CI: `docker compose up -d imap-test` + `make imap-seed`); REQUIRE_IMAP=1 turns the
skip into a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from email.message import EmailMessage
from pathlib import Path

import pytest
from imapclient import IMAPClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account
from app.auth.security import encrypt
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.idle import InboxWatcher
from app.mail.imap import ImapAuthenticator, ImapServer
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import Credentials
from tests.conftest import TEST_REDIS_URL, Client, make_branch, make_personal

HOST = os.environ.get("TEST_IMAP_HOST", "")
PORT = int(os.environ.get("TEST_IMAP_PORT", "1143"))
ROOT = Path(__file__).resolve().parents[2]
USERS = {"pilot": "pilot-test-heslo", "plna": "plna-test-heslo", "senica": "senica-test-heslo"}

pytestmark = [
    pytest.mark.imap,
    pytest.mark.skipif(
        not HOST and os.environ.get("REQUIRE_IMAP") != "1",
        reason="local test IMAP server not configured (set TEST_IMAP_HOST, see tests/integration/README in README.md)",
    ),
]


def addr(user: str) -> str:
    return f"{user}@smartmail.test"


@pytest.fixture(scope="module", autouse=True)
def reseed_senica() -> None:
    if not HOST:
        pytest.fail("REQUIRE_IMAP=1 but TEST_IMAP_HOST is empty")
    cmd = [sys.executable, "tools/seed_test_imap.py", "--host", HOST, "--port", str(PORT), "--reset"]
    subprocess.run([*cmd, "--user", addr("senica")], cwd=ROOT, check=True, capture_output=True)


@pytest.fixture
def settings(migrated: str) -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url=migrated,
        redis_url=TEST_REDIS_URL,
        imap_login_host=HOST,
        imap_login_port=PORT,
        imap_login_security="none",
        internal_domains="smartmail.test",
    )


@pytest.fixture
def mail_server(settings: Settings) -> ImapAuthenticator:  # the real server instead of the fake one
    return ImapAuthenticator(ImapServer.from_settings(settings))


@pytest.fixture
def imap() -> Iterator[IMAPClient]:
    client = IMAPClient(HOST, port=PORT, ssl=False, timeout=10)
    client.login(addr("senica"), USERS["senica"])
    yield client
    client.logout()


async def login(client: Client, user: str) -> None:
    r = await client.login(addr(user), USERS[user])
    assert r.status_code == 200, r.text


async def folders(client: Client) -> dict[str, dict[str, object]]:
    r = await client.get("/api/mail/mailboxes/default/folders")
    assert r.status_code == 200, r.text
    return {f["name"]: f for f in r.json()["folders"]}


async def refresh(client: Client) -> dict[str, object]:
    r = await client.send_json("POST", "/api/mail/mailboxes/default/refresh")
    assert r.status_code == 200, r.text
    body: dict[str, object] = r.json()
    return body


def raw_message(subject: str) -> bytes:
    msg = EmailMessage()
    msg["From"] = "Eva Testovacia <eva@dodavatel.example>"
    msg["To"] = addr("senica")
    msg["Subject"] = subject
    msg["Message-ID"] = "<it-1c@dodavatel.example>"
    msg.set_content("Fiktívna správa pre test synchronizácie.")
    return msg.as_bytes()


async def test_1c_pilot_folder_column_like_roundcube(client: Client) -> None:
    await login(client, "pilot")  # personal account auto-created for an internal domain (D25)
    by_name = await folders(client)
    assert list(by_name) == [
        "INBOX", "Drafts", "Sent", "Junk", "Trash",
        "Archív", "Dodávatelia", "Faktúry", "Kurier", "Nitra", "Senica", "Smart", "Trenčín",
    ]  # fmt: skip
    assert [by_name[n]["special_use"] for n in ("INBOX", "Drafts", "Sent", "Junk", "Trash")] == [
        "inbox", "drafts", "sent", "junk", "trash",
    ]  # fmt: skip
    # PILOT_PLAN INBOX 48/14 + 3 thread pairs (3 unread parents) → 54/17 (Phase 1e seed)
    assert (by_name["INBOX"]["total"], by_name["INBOX"]["unread"]) == (54, 17)
    r = await client.get("/api/mail/mailboxes/default/folders")
    quota = r.json()["quota"]
    assert quota["level"] == "normal" and 30 <= quota["percent"] < 75
    assert r.json()["sync"]["state"] == "ok"
    mailboxes = (await client.get("/api/mail/mailboxes")).json()
    assert mailboxes[0]["unread"] == 17


async def test_g3_quota_above_90_percent_is_danger(client: Client) -> None:
    await login(client, "plna")
    await folders(client)
    quota = (await client.get("/api/mail/mailboxes/default/folders")).json()["quota"]
    assert quota["percent"] >= 90 and quota["level"] == "danger"
    assert quota["limit_kb"] == 2048


async def test_1c_incremental_sync_new_message_flags_and_expunge(
    client: Client, db: AsyncSession, imap: IMAPClient
) -> None:
    await make_branch(db, "Senica", people=1)  # senica@… is a branch mailbox with one person
    acc = (await db.execute(select(Account).where(Account.email == "senica@smartsro.sk"))).scalar_one()
    acc.email = addr("senica")
    await db.commit()
    await login(client, "senica")
    before = (await folders(client))["INBOX"]
    # seed_branch INBOX 28/9 + 1 thread pair (unread parent) → 30/10 (Phase 1e)
    assert (before["total"], before["unread"]) == (30, 10)

    imap.append("INBOX", raw_message("Dodávka č. 77 – potvrdenie"))
    after = {f["name"]: f for f in (await refresh(client))["folders"]}  # type: ignore[attr-defined]
    assert (after["INBOX"]["total"], after["INBOX"]["unread"]) == (31, 11)
    stored = (await db.execute(select(Message).where(Message.message_id == "<it-1c@dodavatel.example>"))).scalar_one()
    assert stored.subject == "Dodávka č. 77 – potvrdenie" and stored.from_email == "eva@dodavatel.example"
    assert not stored.seen

    imap.select_folder("INBOX")
    imap.add_flags([stored.uid], [b"\\Seen"])  # read in Roundcube
    after = {f["name"]: f for f in (await refresh(client))["folders"]}  # type: ignore[attr-defined]
    assert after["INBOX"]["unread"] == 10
    await db.refresh(stored)
    assert stored.seen is True

    imap.delete_messages([stored.uid])
    imap.expunge()
    imap.close_folder()
    after = {f["name"]: f for f in (await refresh(client))["folders"]}  # type: ignore[attr-defined]
    assert after["INBOX"]["total"] == 30
    assert (await db.execute(select(Message).where(Message.id == stored.id))).scalar_one_or_none() is None


async def test_g3_folder_actions_round_trip_on_the_server(client: Client, db: AsyncSession, imap: IMAPClient) -> None:
    await make_personal(db, email=addr("senica"))
    await login(client, "senica")
    await folders(client)

    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": "Reklamácie"})
    assert r.status_code == 200, r.text
    names = [f["name"] for f in r.json()["folders"]]
    assert "Reklamácie" in names and names.index("Reklamácie") > names.index("Nitra")
    assert any(n == "Reklamácie" for *_, n in imap.list_sub_folders())  # visible in Roundcube too

    fid = next(f["id"] for f in r.json()["folders"] if f["name"] == "Reklamácie")
    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": "2026", "parent_id": fid})
    assert r.status_code == 200, r.text
    child = next(f for f in r.json()["folders"] if f["name"] == "Reklamácie/2026")
    assert (child["depth"], child["label"], child["parent_id"]) == (1, "2026", fid)

    r = await client.send_json("PATCH", f"/api/mail/mailboxes/default/folders/{child['id']}", {"name": "Staré"})
    assert r.status_code == 200, r.text
    assert "Reklamácie/Staré" in [f["name"] for f in r.json()["folders"]]

    r = await client.send_json("POST", "/api/mail/mailboxes/default/folders", {"name": "Reklamácie"})
    assert r.status_code == 409

    for name in ("Reklamácie/Staré", "Reklamácie"):
        fid_now = (await db.execute(select(FolderMeta.id).where(FolderMeta.name == name))).scalar_one()
        r = await client.send_json("DELETE", f"/api/mail/mailboxes/default/folders/{fid_now}")
        assert r.status_code == 200, r.text
    assert not any(n.startswith("Reklamácie") for *_, n in imap.list_folders())

    actions = set((await db.execute(select(AuditLog.action))).scalars())
    assert {"mail.folder_created", "mail.folder_renamed", "mail.folder_deleted"} <= actions


async def test_g3_mark_read_and_empty_trash(client: Client, db: AsyncSession, imap: IMAPClient) -> None:
    await make_personal(db, email=addr("senica"))
    await login(client, "senica")
    await folders(client)
    imap.append("Trash", raw_message("Do koša"))
    by_name = {f["name"]: f for f in (await refresh(client))["folders"]}  # type: ignore[attr-defined]
    # seed_branch Trash starts with 3; append → 4
    assert by_name["Trash"]["total"] == 4

    r = await client.send_json("POST", f"/api/mail/mailboxes/default/folders/{by_name['Trash']['id']}/empty")
    assert r.status_code == 200, r.text
    assert next(f for f in r.json()["folders"] if f["name"] == "Trash")["total"] == 0

    r = await client.send_json("POST", f"/api/mail/mailboxes/default/folders/{by_name['INBOX']['id']}/mark-read")
    assert r.status_code == 200, r.text
    assert next(f for f in r.json()["folders"] if f["name"] == "INBOX")["unread"] == 0
    assert imap.folder_status("INBOX", [b"UNSEEN"])[b"UNSEEN"] == 0


async def test_1c_password_changed_on_server_logs_out_everywhere(
    client: Client, db: AsyncSession, settings: Settings
) -> None:
    await login(client, "pilot")
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == addr("pilot")))).scalar_one()
    acc = (await db.execute(select(Account).where(Account.email == addr("pilot")))).scalar_one()
    acc.mailbox_password_enc = encrypt(settings, "stare-heslo")
    await db.commit()
    r = await client.send_json("POST", "/api/mail/mailboxes/default/refresh")
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "password_changed"
    assert (await client.get("/api/auth/me")).status_code == 401
    await db.refresh(mailbox)
    await db.refresh(acc)
    assert mailbox.sync_state == "auth_failed" and acc.mailbox_password_enc is None
    assert "mail.sync_auth_failed" in set((await db.execute(select(AuditLog.action))).scalars())
    # logging in again with the right password resumes the sync
    await login(client, "pilot")
    assert (await client.get("/api/mail/mailboxes/default/folders")).json()["sync"]["state"] == "ok"


def test_1c_idle_watcher_reacts_to_new_inbox_mail(imap: IMAPClient, settings: Settings) -> None:
    pushes = threading.Semaphore(0)
    watcher = InboxWatcher(
        "it",
        ImapServer.from_settings(settings),
        Credentials(addr("senica"), USERS["senica"]),
        on_change=pushes.release,
        on_auth_failed=lambda: None,
        renew_s=60,
        check_every_s=1,
    )
    watcher.start()
    try:
        assert pushes.acquire(timeout=10), "initial catch-up sync was not requested"
        imap.append("INBOX", raw_message("IDLE test"))
        assert pushes.acquire(timeout=10), "IDLE push for the new message did not arrive"
    finally:
        watcher.stop()
        watcher.thread.join(timeout=5)
    assert not watcher.alive
    imap.select_folder("INBOX")
    imap.delete_messages(imap.search(["SUBJECT", "IDLE test"]))
    imap.expunge()
    imap.close_folder()


def test_1c_idle_watcher_stops_on_wrong_password(settings: Settings) -> None:
    failed = threading.Event()
    watcher = InboxWatcher(
        "it",
        ImapServer.from_settings(settings),
        Credentials(addr("senica"), "zle-heslo"),
        on_change=lambda: None,
        on_auth_failed=failed.set,
        renew_s=60,
    )
    watcher.start()
    assert failed.wait(10)
    watcher.thread.join(timeout=5)
    assert not watcher.alive
