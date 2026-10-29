"""Phase 2c approve / reject of reply suggestions: level 2 = a draft in Koncepty, never a send (#94)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AiSuggestion, Classification
from app.api.suggestions import body_to_html
from app.auth.models import Person, Role
from app.core.audit import AuditLog
from app.mail.compose_models import ComposeDraft
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer
from tests.test_mail_messages_1d import _signed_in

PROPOSED = "Dobrý deň,\n\nkópiu faktúry 2026123 Vám pošleme ešte dnes."


async def _seed(db: AsyncSession, mailbox: Mailbox, *, shadow: bool = False) -> tuple[Message, AiSuggestion]:
    folder = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id).limit(1))
    if folder is None:
        folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox", subscribed=True, selectable=True)
        db.add(folder)
        await db.flush()
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=int(uuid4().int % 1_000_000),
        message_id=f"<{uuid4().hex}@abcstav.example>",
        subject="Kópia faktúry",
        from_name="Ján Novák",
        from_email="novak@abcstav.example",
        body_text="Prosím o kópiu faktúry 2026123.",
        flags=[],
    )
    db.add(message)
    await db.flush()
    db.add(
        Classification(
            mailbox_id=mailbox.id,
            message_id=message.id,
            message_id_header=(message.message_id or "").strip("<>"),
            category="invoice_request",
            language="sk",
            status="done",
            payload={"needs_reply": True, "note_codes": []},
        )
    )
    suggestion = AiSuggestion(
        mailbox_id=mailbox.id,
        message_id=message.id,
        suggestion_type="reply",
        payload={"to": ["novak@abcstav.example"], "subject": "Re: Kópia faktúry", "body": PROPOSED, "language": "sk"},
        confidence=Decimal("0.800"),
        shadow=shadow,
    )
    db.add(suggestion)
    await db.commit()
    return message, suggestion


@pytest.fixture
def imap_drafts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    import app.api.suggestions as api

    saved: list[str] = []

    async def fake_sync(db: object, settings: object, draft: ComposeDraft) -> None:
        saved.append(str(draft.id))

    monkeypatch.setattr(api, "sync_draft_to_imap", fake_sync)
    return saved


async def test_2c_approve_prepares_a_reply_draft_in_koncepty_and_sends_nothing(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, imap_drafts: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    message, suggestion = await _seed(db, mailbox)

    r = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["edited"] is False
    await db.close()
    draft = await db.get(ComposeDraft, out["draft_id"])
    assert draft is not None and draft.mode == "reply" and draft.status == "editing"  # not queued, not sent
    assert draft.in_reply_to_message_id == message.id
    assert draft.to_addrs[0]["email"] == "novak@abcstav.example"
    assert "<p>Dobrý deň,</p><p>kópiu faktúry 2026123 Vám pošleme ešte dnes.</p>" in draft.body_html
    assert imap_drafts == [out["draft_id"]]  # APPEND to Koncepty
    row = await db.get(AiSuggestion, suggestion.id)
    assert row is not None and row.status == "approved" and row.decided_by is not None
    assert row.final_payload is not None and row.final_payload["draft_id"] == out["draft_id"]
    assert row.diff == {"edited": False}
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.suggestion_approved"))
    assert entry is not None and entry.details["actor"] == "user" and "body" not in entry.details


async def test_2c_approve_with_an_edited_body_stores_the_diff(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, imap_drafts: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await _seed(db, mailbox)
    r = await client.send_json(
        "POST", f"/api/suggestions/{suggestion.id}/approve", {"body": "Dobrý deň,\n\nfaktúru 2026123 posielame."}
    )
    assert r.status_code == 200, r.text
    assert r.json()["edited"] is True
    await db.close()
    row = await db.get(AiSuggestion, suggestion.id)
    assert row is not None and row.diff is not None and row.diff["edited"] is True
    assert "+faktúru 2026123 posielame." in row.diff["unified"]


async def test_2c_approve_reruns_the_guards(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, imap_drafts: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await _seed(db, mailbox)
    for body in ("Cena je [[DOPLNIŤ: cena]].", "Faktúra 2026999 je uhradená."):
        r = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {"body": body})
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "suggestion_blocked"
    assert imap_drafts == []
    await db.close()
    row = await db.get(AiSuggestion, suggestion.id)
    assert row is not None and row.status == "pending"
    assert (await db.scalar(select(ComposeDraft).limit(1))) is None


async def test_2c_second_decision_is_refused(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, imap_drafts: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await _seed(db, mailbox)
    assert (await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {})).status_code == 200
    again = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "suggestion_decided"
    rejected = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/reject", {"reasons": ["tone"]})
    assert rejected.status_code == 409
    await db.close()
    assert len(list((await db.execute(select(ComposeDraft))).scalars())) == 1


async def test_2c_reject_stores_the_reason_chips(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await _seed(db, mailbox)
    r = await client.send_json(
        "POST",
        f"/api/suggestions/{suggestion.id}/reject",
        {"reasons": ["wrong_data", "tone", "tone"], "note": "  cena je iná  "},
    )
    assert r.status_code == 200, r.text
    await db.close()
    row = await db.get(AiSuggestion, suggestion.id)
    assert row is not None and row.status == "rejected"
    assert row.final_payload == {"reject_reasons": ["wrong_data", "tone"], "note": "cena je iná"}
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.suggestion_rejected"))
    assert entry is not None and entry.details["reasons"] == ["wrong_data", "tone"]
    bad = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/reject", {"reasons": ["bogus"]})
    assert bad.status_code == 422


async def test_2c_shadow_and_foreign_suggestions_are_not_found(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, imap_drafts: list[str]
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _m, shadow = await _seed(db, mailbox, shadow=True)
    other = Mailbox(
        email=f"x-{uuid4().hex[:6]}@smartmail.test", imap_host="localhost", imap_port=1143, imap_security="none"
    )
    db.add(other)
    await db.flush()
    _m2, foreign = await _seed(db, other)
    for sid in (shadow.id, foreign.id, uuid4()):
        r = await client.send_json("POST", f"/api/suggestions/{sid}/approve", {})
        assert r.status_code == 404, r.text
    assert imap_drafts == []


async def test_2c_viewer_cannot_decide(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    _message, suggestion = await _seed(db, mailbox)
    person = await db.scalar(select(Person).where(Person.first_name == "Jana"))
    assert person is not None
    person.role = Role.viewer
    await db.commit()
    r = await client.send_json("POST", f"/api/suggestions/{suggestion.id}/approve", {})
    assert r.status_code == 403


def test_2c_body_to_html_escapes_the_model_text() -> None:
    assert body_to_html("Ahoj <script>x</script>\nriadok 2\n\nOdsek 2") == (
        "<p>Ahoj &lt;script&gt;x&lt;/script&gt;<br>riadok 2</p><p>Odsek 2</p>"
    )
    assert body_to_html("  ") == "<p></p>"
