"""Issue #30: Poslať ďalej keeps the original ordinary attachments.

The draft points at the stored file. Infected parts stay behind. A chip the
user removes is not in the MIME. Fictional files only.
"""

from __future__ import annotations

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.compose import build_mime
from app.mail.compose_models import ComposeDraft, Identity
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
