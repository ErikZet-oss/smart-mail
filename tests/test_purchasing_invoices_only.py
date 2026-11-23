"""Pilot 2026-11-23 — mail intake offers only supplier INVOICES for receipt.

An order confirmation (Auftragsbestätigung) arrived next to every invoice and each delivery showed up twice in
Doklady › Dodacie listy. From mail: invoice → review; delivery note → only with Settings 14 „Spracovať aj dodacie listy
dodávateľa“; order confirmation / other → hidden (status ignored, error not_for_receipt:<kind>). A file uploaded by hand
stays for review. All companies, documents and amounts are fictional.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Classification
from app.auth.models import Role
from app.core.config import Settings
from app.mail import storage
from app.mail.models import Attachment, FolderMeta, Mailbox, Message
from app.purchasing import org_settings
from app.purchasing.intake import intake_supplier_documents
from app.purchasing.models import SupplierDocument
from app.purchasing.pdf_extract import doc_from_tool
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_purchasing_4a import ISDOC, UBL, ToolLLM, _pdf, money_on

__all__ = ["money_on"]  # fixture

NOW = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)


def test_kinds_order_confirmation_and_other_are_kept_unknown_only_when_unsure() -> None:
    assert doc_from_tool({"kind": "order_confirmation", "lines": []}).kind == "order_confirmation"
    assert doc_from_tool({"kind": "other", "lines": []}).kind == "other"
    assert doc_from_tool({"kind": "proforma", "lines": []}).kind == "unknown"


async def _mail(
    db: AsyncSession, settings: Settings, mailbox: Mailbox, uid: int, filename: str, data: bytes, ctype: str
) -> Message:
    box = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert box is not None
    mailbox.ai_enabled = True
    mailbox.ai_enabled_at = datetime(2026, 1, 1, tzinfo=UTC)
    msg = Message(
        mailbox_id=mailbox.id,
        folder_id=box.id,
        uid=uid,
        message_id=f"<doc-{uid}@dodavatel.example>",
        subject=filename,
        from_email="predaj@dodavatel.example",
        to_addrs=[{"email": mailbox.email}],
        body_text="V prílohe doklad.",
        received_at=NOW,
    )
    db.add(msg)
    await db.flush()
    key, sha = storage.put_bytes(settings, data, prefix="test")
    db.add(
        Attachment(
            message_id=msg.id,
            filename=filename,
            content_type=ctype,
            size=len(data),
            storage_key=key,
            sha256=sha,
            av_status="clean",
        )
    )
    db.add(
        Classification(
            mailbox_id=mailbox.id,
            message_id=msg.id,
            message_id_header=f"doc-{uid}@dodavatel.example",
            category="supplier_document",
            language="sk",
            status="done",
        )
    )
    await db.commit()
    return msg


async def _doc(db: AsyncSession, msg: Message) -> SupplierDocument:
    doc = await db.scalar(select(SupplierDocument).where(SupplierDocument.message_id == msg.id))
    assert doc is not None
    return doc


async def test_mail_order_confirmation_is_hidden_and_the_invoice_stays(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.warehouse)
    on = settings.model_copy(update={"feature_money": True, "llm_model_extract": "claude-test"})
    invoice = await _mail(db, settings, mailbox, 81, "FA-2026-00456.isdoc", ISDOC, "application/xml")
    confirmation = await _mail(
        db,
        settings,
        mailbox,
        82,
        "AB-4711.pdf",
        _pdf("<p>Auftragsbestätigung AB-4711, Fiktívny dodávateľ, 100 ks Skrutka DIN 933 M10x30</p>"),
        "application/pdf",
    )
    llm = ToolLLM(
        {
            "kind": "order_confirmation",
            "number": "AB-4711",
            "issued_on": "2026-11-20",
            "lines": [{"name": "Skrutka DIN 933 M10x30", "qty": "100", "unit": "ks"}],
        }
    )
    await intake_supplier_documents(db, mailbox, on, provider=llm)
    await db.commit()
    assert (await _doc(db, invoice)).status in ("needs_review", "missing_data")
    hidden = await _doc(db, confirmation)
    assert hidden.kind == "order_confirmation"
    assert hidden.status == "ignored" and hidden.error == "not_for_receipt:order_confirmation"
    listed = (await client.get("/api/purchasing/documents")).json()
    assert [d["doc_number"] for d in listed["items"]] == ["FA-2026-00456"]  # only the invoice is open


@pytest.mark.parametrize("accept", [False, True])
async def test_mail_delivery_note_only_when_switched_on(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, accept: bool
) -> None:
    mailbox = await _signed_in(client, db, mail_server, role=Role.warehouse)
    conf = await org_settings.load(db)
    await org_settings.save(db, conf.model_copy(update={"accept_delivery_notes": accept}))
    await db.commit()
    on = settings.model_copy(update={"feature_money": True})
    msg = await _mail(db, settings, mailbox, 83, "DL-2026-0099.xml", UBL, "application/xml")
    await intake_supplier_documents(db, mailbox, on)
    await db.commit()
    doc = await _doc(db, msg)
    assert doc.kind == "delivery_note"
    if accept:
        assert doc.status != "ignored" and doc.error is None
    else:
        assert doc.status == "ignored" and doc.error == "not_for_receipt:delivery_note"


async def test_uploaded_delivery_note_stays_for_review(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, app: Any
) -> None:
    await _signed_in(client, db, mail_server, role=Role.warehouse)
    app.state.settings.feature_money = True
    try:
        await client.csrf()
        r = await client.post(
            "/api/purchasing/documents",
            files={"file": ("DL-2026-0099.xml", UBL, "application/xml")},
            headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
        )
    finally:
        app.state.settings.feature_money = False
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "delivery_note" and r.json()["status"] != "ignored"


async def test_settings_14_switch_is_off_by_default(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, money_on: None
) -> None:
    await _signed_in(client, db, mail_server, role=Role.admin)
    body = (await client.get("/api/settings/purchasing")).json()
    assert body["accept_delivery_notes"] is False
