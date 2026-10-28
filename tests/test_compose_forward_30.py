"""Issue #30: Poslať ďalej keeps the original ordinary attachments.

The draft points at the stored file. Infected parts stay behind. A chip the
user removes is not in the MIME. Send re-reads the source antivirus status.
Fictional files only.
"""

from __future__ import annotations

import json
import uuid
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.compose import PENDING_AV_WARNING, AttachmentNotSendable, build_mime, execute_send
from app.mail.compose_models import ComposeAttachment, ComposeDraft, Identity
from app.mail.models import Attachment, Mailbox, Message
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import NOW, PASSWORD, delta, env, snapshot

_PDF = b"%PDF-1.4 fictional order"
_UNCHECKED = b"%PDF-1.4 fictional unchecked"
_ERROR = b"%PDF-1.4 fictional scan error"
_INFECTED = b"INFECTED-FICTIONAL-BYTES"


def _payloads(message: EmailMessage) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for part in message.walk():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            found[filename] = payload
    return found


@pytest.mark.asyncio
async def test_issue30_forward_copies_pdf_skips_infected_and_honours_remove(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    account = await make_personal(db)
    mail_server.passwords[account.email] = PASSWORD
    assert (await client.login(account.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == account.email))).scalar_one()
    from app.mail.sync import apply_snapshot

    snap = snapshot(
        delta("INBOX", 1, 2, 1, 1, new=[env(1, subject="Faktúra fiktívna")], present_uids={1}),
        folders=("INBOX", "Drafts", "Sent"),
    )
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await db.commit()
    msg = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    pdf_key, pdf_sha = storage.put_bytes(settings, _PDF, prefix=f"mail/{mailbox.id}/att")
    unchecked_key, unchecked_sha = storage.put_bytes(settings, _UNCHECKED, prefix=f"mail/{mailbox.id}/att")
    error_key, error_sha = storage.put_bytes(settings, _ERROR, prefix=f"mail/{mailbox.id}/att")
    infected_key, infected_sha = storage.put_bytes(settings, _INFECTED, prefix=f"mail/{mailbox.id}/att")
    db.add(
        Attachment(
            message_id=msg.id,
            filename="objednavka-fiktivna.pdf",
            content_type="application/pdf",
            storage_key=pdf_key,
            sha256=pdf_sha,
            size=len(_PDF),
            is_inline=False,
            av_status="clean",
        )
    )
    db.add(
        Attachment(
            message_id=msg.id,
            filename="neskenovane-fiktivne.pdf",
            content_type="application/pdf",
            storage_key=unchecked_key,
            sha256=unchecked_sha,
            size=len(_UNCHECKED),
            is_inline=False,
            av_status="skipped",
        )
    )
    db.add(
        Attachment(
            message_id=msg.id,
            filename="chyba-skenu-fiktivne.pdf",
            content_type="application/pdf",
            storage_key=error_key,
            sha256=error_sha,
            size=len(_ERROR),
            is_inline=False,
            av_status="error",
        )
    )
    db.add(
        Attachment(
            message_id=msg.id,
            filename="virus-fiktivny.pdf",
            content_type="application/pdf",
            storage_key=infected_key,
            sha256=infected_sha,
            size=len(_INFECTED),
            is_inline=False,
            av_status="infected",
        )
    )
    await db.commit()

    created = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/compose",
        {"mode": "forward", "message_id": str(msg.id)},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    names = {item["filename"]: item for item in body["attachments"]}
    assert set(names) == {
        "objednavka-fiktivna.pdf",
        "neskenovane-fiktivne.pdf",
        "chyba-skenu-fiktivne.pdf",
    }
    assert names["objednavka-fiktivna.pdf"]["av_status"] == "clean"
    assert names["neskenovane-fiktivne.pdf"]["av_status"] == "skipped"
    assert names["chyba-skenu-fiktivne.pdf"]["av_status"] == "error"
    assert "virus-fiktivny.pdf" not in names
    draft_id = body["id"]

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    mime = await build_mime(db, settings, draft, identity)
    payloads = _payloads(mime)
    assert payloads["objednavka-fiktivna.pdf"] == _PDF
    assert payloads["neskenovane-fiktivne.pdf"] == _UNCHECKED
    assert payloads["chyba-skenu-fiktivne.pdf"] == _ERROR
    assert "virus-fiktivny.pdf" not in payloads

    removed = await client.send_json(
        "DELETE",
        f"/api/mail/compose/{draft_id}/attachments/{names['objednavka-fiktivna.pdf']['id']}",
    )
    assert removed.status_code == 200, removed.text
    left = {item["filename"] for item in removed.json()["attachments"]}
    assert left == {"neskenovane-fiktivne.pdf", "chyba-skenu-fiktivne.pdf"}
    assert storage.get_bytes(settings, pdf_key) == _PDF

    mime_after = await build_mime(db, settings, draft, identity)
    after = _payloads(mime_after)
    assert "objednavka-fiktivna.pdf" not in after
    assert after["neskenovane-fiktivne.pdf"] == _UNCHECKED


_PENDING = b"%PDF-1.4 fictional pending scan"


async def _mailbox(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Mailbox:
    account = await make_personal(db)
    mail_server.passwords[account.email] = PASSWORD
    assert (await client.login(account.email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == account.email))).scalar_one()


async def _inbox_message(db: AsyncSession, mailbox: Mailbox) -> Message:
    from app.mail.sync import apply_snapshot

    snap = snapshot(
        delta("INBOX", 1, 2, 1, 1, new=[env(1, subject="Správa fiktívna")], present_uids={1}),
        folders=("INBOX", "Drafts", "Sent"),
    )
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await db.commit()
    return (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()


async def _forward_file(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    *,
    filename: str,
    data: bytes,
    av_status: str,
) -> tuple[Message, Attachment, str]:
    mailbox = await _mailbox(client, db, mail_server)
    msg = await _inbox_message(db, mailbox)
    key, digest = storage.put_bytes(settings, data, prefix=f"mail/{mailbox.id}/att")
    source = Attachment(
        message_id=msg.id,
        filename=filename,
        content_type="application/pdf",
        storage_key=key,
        sha256=digest,
        size=len(data),
        is_inline=False,
        av_status=av_status,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    created = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/compose",
        {"mode": "forward", "message_id": str(msg.id)},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "kolega@smartsro.sk", "name": "Kolega"}],
            "subject": "Posielam ďalej",
            "body_html": "<p>Fiktívna správa.</p>",
        },
    )
    assert patched.status_code == 200, patched.text
    return msg, source, draft_id


def _pending_check(checks: list[dict[str, object]]) -> dict[str, object]:
    return next(item for item in checks if item["code"] == "attachment_pending")


def test_30_pending_warning_matches_slovak_copy() -> None:
    sk = json.loads(Path("web/src/i18n/sk.json").read_text(encoding="utf-8"))
    assert sk["compose"]["checks"]["attachment_pending"] == PENDING_AV_WARNING
    assert sk["compose"]["attachmentPending"] == PENDING_AV_WARNING


@pytest.mark.asyncio
async def test_30_forward_pending_then_infected_blocks_send(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    _msg, source, draft_id = await _forward_file(
        client,
        db,
        mail_server,
        settings,
        filename="cakajuci-sken-fiktivny.pdf",
        data=_PENDING,
        av_status="pending",
    )
    opened = await client.get(f"/api/mail/compose/{draft_id}")
    assert opened.status_code == 200, opened.text
    assert opened.json()["attachments"][0]["av_status"] == "pending"
    copied = await db.get(ComposeAttachment, uuid.UUID(opened.json()["attachments"][0]["id"]))
    assert copied is not None
    assert copied.av_status == "pending"

    source.av_status = "infected"
    await db.commit()

    refreshed = await client.get(f"/api/mail/compose/{draft_id}")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["attachments"][0]["av_status"] == "infected"
    await db.refresh(copied)
    assert copied.av_status == "pending"

    with patch("app.mail.compose.send_message", new_callable=AsyncMock) as send:
        blocked = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": True})
        assert blocked.status_code == 409, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "attachment_infected"
        assert detail["filename"] == "cakajuci-sken-fiktivny.pdf"
        send.assert_not_awaited()

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "editing"
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    with pytest.raises(AttachmentNotSendable) as exc:
        await build_mime(db, settings, draft, identity)
    assert exc.value.code == "attachment_infected"
    assert exc.value.filename == "cakajuci-sken-fiktivny.pdf"

    draft.status = "queued"
    draft.undo_until = None
    await db.commit()
    with patch("app.mail.compose.send_message", new_callable=AsyncMock) as send:
        result = await execute_send(db, settings, draft.id)
        assert result == "failed"
        send.assert_not_awaited()
    await db.refresh(draft)
    assert draft.status == "failed"
    assert draft.send_error is not None
    assert draft.send_error.startswith("attachment_infected:")


@pytest.mark.asyncio
async def test_30_pending_attachment_warns(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    _msg, _source, draft_id = await _forward_file(
        client,
        db,
        mail_server,
        settings,
        filename="cakajuci-sken-fiktivny.pdf",
        data=_PENDING,
        av_status="pending",
    )
    opened = await client.get(f"/api/mail/compose/{draft_id}")
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["attachments"][0]["av_status"] == "pending"
    warn = _pending_check(body["checks"])
    assert warn["blocking"] is False
    assert warn["message"] == PENDING_AV_WARNING

    with patch("app.mail.compose.send_message", new_callable=AsyncMock) as send:
        blocked = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": False})
        assert blocked.status_code == 409, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "pre_send_blocked"
        again = _pending_check(detail["checks"])
        assert again["blocking"] is False
        assert again["message"] == PENDING_AV_WARNING
        send.assert_not_awaited()

        confirmed = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": True})
        assert confirmed.status_code == 200, confirmed.text
        send.assert_awaited()
        mime = send.await_args.args[1]
        assert isinstance(mime, EmailMessage)
        assert _payloads(mime)["cakajuci-sken-fiktivny.pdf"] == _PENDING


@pytest.mark.asyncio
async def test_30_missing_blob_blocks_send(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    _msg, source, draft_id = await _forward_file(
        client,
        db,
        mail_server,
        settings,
        filename="chybajuci-subor-fiktivny.pdf",
        data=_PDF,
        av_status="clean",
    )
    storage.delete_key(settings, source.storage_key)
    with patch("app.mail.compose.send_message", new_callable=AsyncMock) as send:
        blocked = await client.send_json("POST", f"/api/mail/compose/{draft_id}/send", {"force": True})
        assert blocked.status_code == 409, blocked.text
        detail = blocked.json()["detail"]
        assert detail["code"] == "attachment_missing"
        assert detail["filename"] == "chybajuci-subor-fiktivny.pdf"
        send.assert_not_awaited()

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    assert draft.status == "editing"
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    with pytest.raises(AttachmentNotSendable) as exc:
        await build_mime(db, settings, draft, identity)
    assert exc.value.code == "attachment_missing"
    assert exc.value.filename == "chybajuci-subor-fiktivny.pdf"
