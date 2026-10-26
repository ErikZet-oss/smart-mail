"""Phase 1d against the local test IMAP server (docker compose `imap-test`, Dovecot).

Covers message list, conversation threading, lazy body fetch, and attachment download for fictional mail only.
Never talks to live company mailboxes.

Runs when TEST_IMAP_HOST is set (CI: `docker compose up -d imap-test` + `make imap-seed`); REQUIRE_IMAP=1 turns the
skip into a failure.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

import pytest
from imapclient import IMAPClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.imap import ImapAuthenticator, ImapServer
from app.mail.models import Attachment, FolderMeta, Message, Thread
from tests.conftest import TEST_REDIS_URL, Client, make_personal

HOST = os.environ.get("TEST_IMAP_HOST", "")
PORT = int(os.environ.get("TEST_IMAP_PORT", "1143"))
ROOT = Path(__file__).resolve().parents[2]
USERS = {"pilot": "pilot-test-heslo", "senica": "senica-test-heslo"}
DOMAIN = "smartmail.test"

pytestmark = [
    pytest.mark.imap,
    pytest.mark.skipif(
        not HOST and os.environ.get("REQUIRE_IMAP") != "1",
        reason="local test IMAP server not configured (set TEST_IMAP_HOST, see README)",
    ),
]


def addr(user: str) -> str:
    return f"{user}@{DOMAIN}"


@pytest.fixture(scope="module", autouse=True)
def reseed_senica() -> None:
    if not HOST:
        pytest.fail("REQUIRE_IMAP=1 but TEST_IMAP_HOST is empty")
    cmd = [sys.executable, "tools/seed_test_imap.py", "--host", HOST, "--port", str(PORT), "--reset"]
    subprocess.run([*cmd, "--user", addr("senica")], cwd=ROOT, check=True, capture_output=True)


@pytest.fixture
def settings(migrated: str, tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url=migrated,
        redis_url=TEST_REDIS_URL,
        imap_login_host=HOST,
        imap_login_port=PORT,
        imap_login_security="none",
        internal_domains=DOMAIN,
        storage_path=str(tmp_path / "storage"),
    )


@pytest.fixture
def mail_server(settings: Settings) -> ImapAuthenticator:
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


def thread_pair_with_attachment() -> tuple[bytes, bytes]:
    """Parent + reply (Message-ID graph) and a small fictional PDF on the parent."""
    parent_id = make_msgid(domain="dodavatel.example")
    sent = datetime(2026, 10, 26, 10, 0, tzinfo=UTC)

    parent = EmailMessage()
    parent["From"] = "Eva Testovacia <eva@dodavatel.example>"
    parent["To"] = addr("senica")
    parent["Subject"] = "Dodací list DL-1d-77"
    parent["Date"] = format_datetime(sent)
    parent["Message-ID"] = parent_id
    parent.set_content(
        "Dobrý deň,\n\ntoto je fiktívny dodací list pre Phase 1d (list, vlákno, telo, príloha).\n\nS pozdravom\nEva\n"
    )
    parent.add_attachment(
        b"%PDF-1.4 fictional-smart-mail-1d-attachment\n",
        maintype="application",
        subtype="pdf",
        filename="dodaci-list-1d-77.pdf",
    )

    reply = EmailMessage()
    reply["From"] = addr("senica")
    reply["To"] = "Eva Testovacia <eva@dodavatel.example>"
    reply["Subject"] = "Re: Dodací list DL-1d-77"
    reply["Date"] = format_datetime(datetime(2026, 10, 26, 11, 0, tzinfo=UTC))
    reply["Message-ID"] = make_msgid(domain=DOMAIN)
    reply["In-Reply-To"] = parent_id
    reply["References"] = parent_id
    reply.set_content("Ďakujeme, fiktívna odpoveď vo vlákne Phase 1d.\n")
    return parent.as_bytes(), reply.as_bytes()


async def test_1d_list_thread_body_and_attachment(
    client: Client, db: AsyncSession, imap: IMAPClient, settings: Settings
) -> None:
    await make_personal(db, email=addr("senica"))
    await login(client, "senica")
    by_name = await folders(client)
    inbox_id = by_name["INBOX"]["id"]
    assert isinstance(inbox_id, str)

    parent_raw, reply_raw = thread_pair_with_attachment()
    imap.append("INBOX", parent_raw)
    imap.append("INBOX", reply_raw)
    await refresh(client)

    listed = await client.get(f"/api/mail/mailboxes/default/folders/{inbox_id}/messages")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["mode"] == "list"
    assert body["total"] >= 2
    subjects = [m["subject"] for m in body["messages"]]
    assert "Dodací list DL-1d-77" in subjects
    assert "Re: Dodací list DL-1d-77" in subjects
    parent_row = next(m for m in body["messages"] if m["subject"] == "Dodací list DL-1d-77")
    assert parent_row["from_email"] == "eva@dodavatel.example"
    # has_attachments flips true only after lazy body fetch (envelope sync has no BODYSTRUCTURE)

    prefs = await client.send_json("PUT", "/api/mail/prefs", {"list": {"mode": "conversations"}})
    assert prefs.status_code == 200
    conv = await client.get(f"/api/mail/mailboxes/default/folders/{inbox_id}/messages")
    assert conv.status_code == 200, conv.text
    threads = conv.json()["threads"]
    hit = next(
        (t for t in threads if t["subject"] in ("Dodací list DL-1d-77", "Re: Dodací list DL-1d-77")),
        None,
    )
    assert hit is not None
    assert hit["message_count"] >= 2

    stored = (await db.execute(select(Message).where(Message.subject == "Dodací list DL-1d-77"))).scalar_one()
    detail = await client.get(
        f"/api/mail/mailboxes/default/messages/{stored.id}",
        params={"mark_read": "false"},
    )
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["body_text"] is not None
    assert "fiktívny dodací list" in payload["body_text"]
    assert payload["attachments"], "parent must expose the fictional PDF after lazy body fetch"
    att = payload["attachments"][0]
    assert att["filename"] == "dodaci-list-1d-77.pdf"
    assert att["content_type"].startswith("application/pdf")
    assert att["size"] > 0

    await db.refresh(stored)
    assert stored.body_fetched_at is not None
    assert stored.raw_storage_key
    assert stored.has_attachments is True
    thread = await db.scalar(select(Thread).where(Thread.id == stored.thread_id))
    assert thread is not None
    assert (await db.scalar(select(Attachment).where(Attachment.message_id == stored.id))) is not None

    download = await client.get(f"/api/mail/mailboxes/default/attachments/{att['id']}")
    assert download.status_code == 200, download.text
    assert b"fictional-smart-mail-1d-attachment" in download.content
    assert "pdf" in (download.headers.get("content-type") or "").lower()

    folder = await db.scalar(select(FolderMeta).where(FolderMeta.id == stored.folder_id))
    assert folder is not None and folder.name == "INBOX"
    assert settings.storage_path  # local driver for 1d (S3 deferred to 1e+)
