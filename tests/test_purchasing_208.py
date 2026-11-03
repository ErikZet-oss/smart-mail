"""#208 AI card „Príjem tovaru“ in the mail thread: the supplier documents of one message (read-only, no Money write).
All companies, articles and amounts are fictional."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.core.config import Settings
from app.purchasing.intake import intake_supplier_documents
from app.purchasing.models import SupplierDocument
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD, _signed_in
from tests.test_purchasing_4a import _mail_with_attachment, _supplier, money_on
from tests.test_purchasing_4b import A_BOLT, ArticleBridge, _bridge, _sc

__all__ = ["_bridge", "money_on"]


async def _doc_for_mail(client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings) -> Any:
    mailbox = await _signed_in(client, db, mail_server, role=Role.warehouse)
    await _supplier(db)
    msg = await _mail_with_attachment(db, settings, mailbox, "INBOX")
    await intake_supplier_documents(db, mailbox, settings.model_copy(update={"feature_money": True}))
    await db.commit()
    return msg


def _url(msg: Any) -> str:
    return f"/api/purchasing/mailboxes/default/messages/{msg.id}/documents"


async def test_208_card_counts_and_checks_of_the_message(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    ArticleBridge.codes = [_sc("933-10-30-A2", A_BOLT)]  # line 1 by supplier code, line 2 by text only
    msg = await _doc_for_mail(client, db, mail_server, settings)
    r = await client.get(_url(msg))
    assert r.status_code == 200, r.text
    [card] = r.json()
    assert card["supplier_name"] == "Fiktívny dodávateľ s.r.o." and card["supplier_in_money"] is True
    assert card["doc_number"] == "FA-2026-00456" and card["filename"] == "FA-2026-00456.isdoc"
    assert (card["lines"], card["matched"], card["to_confirm"], card["unmatched"]) == (2, 1, 0, 1)
    assert card["matching_done"] is True and card["money_available"] is True
    assert any(c["id"] == "DL-B4" for c in card["checks"])


async def test_208_money_down_card_still_answers(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    ArticleBridge.down = True
    msg = await _doc_for_mail(client, db, mail_server, settings)
    [card] = (await client.get(_url(msg))).json()
    assert card["money_available"] is False and card["supplier_in_money"] is None
    assert card["matching_done"] is False and card["lines"] == 2


async def test_208_ignored_document_is_not_returned(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    msg = await _doc_for_mail(client, db, mail_server, settings)
    doc = await db.scalar(select(SupplierDocument).where(SupplierDocument.message_id == msg.id))
    assert doc is not None
    r = await client.send_json("POST", f"/api/purchasing/documents/{doc.id}/ignore", {})
    assert r.status_code == 200
    assert (await client.get(_url(msg))).json() == []


async def test_208_roles_feature_flag_and_other_mailboxes(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    money_on: None,
    app: FastAPI,
) -> None:
    msg = await _doc_for_mail(client, db, mail_server, settings)
    app.state.settings.feature_money = False
    assert (await client.get(_url(msg))).json() == []  # Money off → no card, the mail keeps working
    app.state.settings.feature_money = True
    assert (await client.get(f"/api/purchasing/mailboxes/default/messages/{uuid.uuid4()}/documents")).status_code == 404
    # another login without access to this mailbox
    await client.post("/api/auth/logout")
    other = await make_personal(db, email="iny@smartsro.sk", role=Role.warehouse)
    mail_server.passwords[other.email] = PASSWORD
    assert (await client.login(other.email, PASSWORD)).status_code == 200
    assert (await client.get(_url(msg))).status_code == 404
