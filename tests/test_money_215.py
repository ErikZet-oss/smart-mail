"""#215 (ADR-019) another company's invoice: offered with a red `requires_ack` check, sent only after a person ticks
„Overil som…“, never in a batch. Fictional companies and numbers only (never the pilot's real ones)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail import storage
from app.mail.compose import attachment_send_block
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.money.invoice_attach import evaluate, marked_company, storage_prefix
from app.money.invoice_suggest import suggest_invoice_attach
from app.money.schemas import InvoiceSearch
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in
from tests.test_money_3d import OTHER, OURS, FakeBridge, _companies, _fake_bridge, _message, inv, money_on

__all__ = ["_fake_bridge", "money_on"]

ACK = {"acknowledged_checks": ["invoice_other_customer"]}


@pytest.fixture(autouse=True)
def _order_search(monkeypatch: pytest.MonkeyPatch) -> None:
    original = FakeBridge.search_invoices

    async def search(self: Any, *, order: str | None = None, **kw: Any) -> InvoiceSearch:
        if order:
            rows = [i for i in FakeBridge.invoices if order in (i.description or "")]
            return InvoiceSearch(matched_by="order" if rows else "none", items=rows)
        return await original(self, number=kw.get("number"), vs=kw.get("vs"))

    monkeypatch.setattr(FakeBridge, "search_invoices", search)


def _ack(row: AiSuggestion) -> dict[str, Any]:
    return next(c for c in row.checks if c["id"] == "invoice_other_customer")


async def test_215_ack_evaluate_names_owner_and_requester_only_when_allowed(
    db: AsyncSession, settings: Settings
) -> None:
    await _companies(db)
    bridge = FakeBridge()
    FakeBridge.invoices = [inv("FV2600099", OTHER), inv("FV2600042", OURS)]
    ev = await evaluate(
        db,
        settings,
        bridge,
        email="faktury@firma1.example",
        body_text=None,
        refs=["FV2600099"],
        language="sk",
        allow_other_owner=True,
    )  # type: ignore[arg-type]
    assert ev.foreign and ev.owner_money_id == OTHER and [i.number for i in ev.invoices] == ["FV2600099"]
    check = next(c for c in ev.checks if c["id"] == "invoice_other_customer")
    assert check["level"] == "requires_ack"
    assert check["params"]["owner"] == "Fiktívna 2 s.r.o." and check["params"]["requester"] == "Fiktívna 1 s.r.o."
    assert not ev.blocked and ev.marker_company == OTHER
    # without the permission (e.g. „the last invoice“) nothing changes: blocked, the other company is not named
    old = await evaluate(
        db, settings, bridge, email="faktury@firma1.example", body_text=None, refs=["FV2600099"], language="sk"
    )  # type: ignore[arg-type]
    assert old.blocked and not old.invoices and "Fiktívna 2" not in str(old.checks)
    # own invoice → no ack at all
    own = await evaluate(
        db,
        settings,
        bridge,
        email="faktury@firma1.example",
        body_text=None,
        refs=["FV2600042"],
        language="sk",
        allow_other_owner=True,
    )  # type: ignore[arg-type]
    assert not own.foreign and not any(c["level"] == "requires_ack" for c in own.checks)


async def test_215_ack_unknown_sender_gets_one_tick_not_two(db: AsyncSession, settings: Settings) -> None:
    await _companies(db)
    FakeBridge.invoices = [inv("FV2600099", OTHER)]
    ev = await evaluate(
        db,
        settings,
        FakeBridge(),
        email="niekto@gmail.example",
        body_text=None,
        refs=["FV2600099"],
        language="sk",
        allow_other_owner=True,
    )  # type: ignore[arg-type]
    assert ev.foreign and not ev.blocked
    assert not any(c["id"] == "recipient_unconfirmed" for c in ev.checks)  # merged into the one tick
    assert _ack_params(ev.checks)["requester"] == "niekto@gmail.example"


def _ack_params(checks: list[dict[str, Any]]) -> dict[str, Any]:
    return next(c["params"] for c in checks if c["id"] == "invoice_other_customer")


async def test_215_ack_card_by_number_and_by_order_but_never_for_the_last_invoice(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    on = settings.model_copy(update={"feature_money": True})
    FakeBridge.invoices = [inv("FV2600099", OTHER).model_copy(update={"description": "Objednávka 2410000099"})]
    msg = await _message(db, mailbox, "faktury@firma1.example", "Pošlite faktúru k objednávke 2410000099.")
    await suggest_invoice_attach(db, mailbox, on, shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.message_id == msg.id))
    assert row is not None and row.payload["foreign"] is True and row.batch_safe is False
    assert _ack(row)["level"] == "requires_ack" and row.payload["owner_name"] == "Fiktívna 2 s.r.o."


async def test_215_ack_last_invoice_of_an_unknown_sender_gives_no_card(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [inv("FV2600099", OTHER)]
    await _message(db, mailbox, "niekto@gmail.example", "Pošlite poslednú faktúru.")
    stats = await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    assert stats["created"] == 0 and await db.scalar(select(AiSuggestion)) is None


async def _foreign_card(client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings) -> Any:
    mailbox = await _signed_in(client, db, mail_server)
    await _companies(db)
    FakeBridge.invoices = [inv("FV2600099", OTHER)]
    await _message(db, mailbox, "faktury@firma1.example", "Prosím kópiu faktúry FV2600099.")
    await suggest_invoice_attach(db, mailbox, settings.model_copy(update={"feature_money": True}), shadow=False)
    await db.commit()
    row = await db.scalar(select(AiSuggestion).where(AiSuggestion.suggestion_type == "invoice_attach"))
    assert row is not None and row.payload["foreign"] is True
    return row


async def test_215_ack_approve_needs_the_tick_then_sends_only_with_it(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    row = await _foreign_card(client, db, mail_server, settings)
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "ack_required"
    assert await db.scalar(select(ComposeDraft)) is None

    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", ACK)
    assert r.status_code == 200, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None and [a["email"] for a in draft.to_addrs] == ["faktury@firma1.example"]
    att = await db.scalar(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))
    assert att is not None and marked_company(att.storage_key) == OTHER  # bound to the invoice's own customer
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "money.invoice_other_customer_ack"))
    assert entry is not None and entry.person_id is not None and entry.account_id is not None
    assert entry.details["invoices"] == ["FV2600099"] and entry.details["owner_money_id"] == str(OTHER)
    assert entry.details["requester_email"] == "faktury@firma1.example"

    await db.refresh(row)
    await db.refresh(row)  # this test session cached the suggestion before approve
    # send guard: the acknowledged draft passes …
    assert await attachment_send_block(db, settings, draft) is None
    # an unrelated draft with the same foreign invoice attached by hand has no ack → blocked as before
    other = ComposeDraft(
        mailbox_id=draft.mailbox_id,
        account_id=draft.account_id,
        to_addrs=[{"email": "faktury@firma1.example"}],
        status="editing",
    )
    db.add(other)
    await db.flush()
    db.add(
        ComposeAttachment(
            draft_id=other.id,
            filename="Faktura_FV2600099.pdf",
            content_type="application/pdf",
            size=att.size,
            storage_key=storage.put_bytes(settings, b"%PDF-1.4 fiktivne", prefix=storage_prefix(other.id, OTHER))[0],
            sha256=att.sha256,
            av_status="clean",
        )
    )
    await db.commit()
    blocked = await attachment_send_block(db, settings, other)
    assert blocked is not None and blocked.code == "recipient_not_document_owner"


async def test_215_ack_owner_changed_between_card_and_approve(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    row = await _foreign_card(client, db, mail_server, settings)
    third = uuid.uuid5(uuid.NAMESPACE_URL, "company-third")
    FakeBridge.invoices = [inv("FV2600099", third)]  # Money moved the invoice to yet another customer
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", ACK)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "suggestion_blocked"
    FakeBridge.invoices = []  # deleted in Money
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", ACK)
    assert r.status_code == 409
    assert await db.scalar(select(ComposeDraft)) is None


async def test_215_ack_is_never_batch_safe(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    row = await _foreign_card(client, db, mail_server, settings)
    assert row.batch_safe is False  # batch approve (Phase 5) only takes batch_safe suggestions


async def _acked_draft(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> tuple[ComposeDraft, Any]:
    row = await _foreign_card(client, db, mail_server, settings)
    r = await client.send_json("POST", f"/api/suggestions/{row.id}/approve", ACK)
    assert r.status_code == 200, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None
    await db.refresh(draft)
    await db.refresh(row)  # this test session cached the suggestion before approve
    assert await attachment_send_block(db, settings, draft) is None  # baseline: the acknowledged draft passes
    return draft, row


@pytest.mark.parametrize("field", ["to_addrs", "cc_addrs", "bcc_addrs"])
async def test_215_ack_extra_external_recipient_is_blocked(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None, field: str
) -> None:
    draft, _ = await _acked_draft(client, db, mail_server, settings)
    setattr(draft, field, [*(getattr(draft, field) or []), {"email": "niekto.iny@gmail.example"}])
    await db.commit()
    blocked = await attachment_send_block(db, settings, draft)
    assert blocked is not None and blocked.code == "recipient_not_document_owner"


async def test_215_ack_confirmed_address_plus_internal_copy_passes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    draft, _ = await _acked_draft(client, db, mail_server, settings)
    draft.cc_addrs = [{"email": f"kolega@{settings.internal_domain_list[0]}"}]
    await db.commit()
    assert await attachment_send_block(db, settings, draft) is None


async def test_215_ack_confirmed_address_changed_is_blocked(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, money_on: None
) -> None:
    draft, row = await _acked_draft(client, db, mail_server, settings)
    assert row.final_payload["ack"]["email"] == "faktury@firma1.example"
    draft.to_addrs = [{"email": "faktury2@firma1.example"}]
    await db.commit()
    blocked = await attachment_send_block(db, settings, draft)
    assert blocked is not None and blocked.code == "recipient_not_document_owner"
