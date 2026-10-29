"""Issue #65: the signature person of a draft („Odpovedá: … ▾“). Changing it swaps only the signature block (typed text
and the quote stay), only persons of this login may sign, and a one-off edited signature is replaced only after a
confirmation. The sent MIME carries the new person's signature."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Person
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.compose import build_mime
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.models import Mailbox, Message
from app.mail.sanitize import signature_span
from tests.conftest import Client, FakeMailServer, make_branch
from tests.test_mail_messages_1d import _seed_inbox
from tests.test_mail_sync_1c import env
from tests.test_persons_1b import choose, login_branch, senica

TEMPLATE = {"sk": "<p>{meno} {priezvisko} – {pobocka}</p>"}


async def _reply_draft(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> tuple[dict[str, Person], str]:
    _, acc, people = await senica(db, signature_template_html=TEMPLATE)
    await login_branch(client, mail_server, acc)
    await choose(client, people["jana"])
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    folder = await _seed_inbox(db, mailbox, env(1, subject="Objednávka 4471"))
    source = await db.scalar(select(Message).where(Message.folder_id == folder.id))
    assert source is not None
    source.body_html_sanitized = "<p>Pôvodná objednávka 4471: 2 000 ks M10</p>"
    await db.commit()
    r = await client.send_json(
        "POST", "/api/mail/mailboxes/default/compose", {"mode": "reply", "message_id": str(source.id)}
    )
    assert r.status_code == 200, r.text
    assert "Jana Nováková" in r.json()["body_html"]
    return people, r.json()["id"]


def _signature(html: str) -> str:
    span = signature_span(html)
    assert span is not None
    return span[1]


async def test_65_changing_the_signature_person_swaps_only_the_signature_block(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    people, draft_id = await _reply_draft(client, db, mail_server)
    typed = "<p>Dobrý deň, potvrdzujeme.</p>"
    r = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {"body_html": typed, "signature_person_id": str(people["marek"].id)},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["signature_person_id"] == str(people["marek"].id)
    assert out["signature_person_name"] == "Marek Kováč"
    assert "Marek Kováč – Senica" in _signature(out["body_html"])
    assert "Jana" not in _signature(out["body_html"])
    assert "Dobrý deň, potvrdzujeme." in out["body_html"]
    assert "Pôvodná objednávka 4471" in out["body_html"]  # the quote stays

    # the sent MIME carries the new person's signature
    draft = await db.get(ComposeDraft, uuid.UUID(draft_id), populate_existing=True)
    assert draft is not None
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    html = (await build_mime(db, settings, draft, identity)).get_body(preferencelist=("html",))
    assert html is not None
    content = html.get_content()
    assert "Marek Kováč – Senica" in content and "Jana Nováková –" not in content

    row = (
        await db.execute(
            select(AuditLog)
            .where(AuditLog.action == "mail.compose_signature_person")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.details == {"before": str(people["jana"].id), "after": str(people["marek"].id)}


async def test_65_a_person_who_is_not_eligible_for_this_login_gets_422(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, draft_id = await _reply_draft(client, db, mail_server)
    nitra, _ = await make_branch(db, "Nitra", people=1)
    stranger = (await db.execute(select(Person).where(Person.branch_id == nitra.id))).scalar_one()
    r = await client.send_json("PATCH", f"/api/mail/compose/{draft_id}", {"signature_person_id": str(stranger.id)})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "signature_person_not_allowed"


async def test_65_an_edited_signature_is_replaced_only_after_confirmation(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    people, draft_id = await _reply_draft(client, db, mail_server)
    r = await client.send_json(
        "PATCH", f"/api/mail/compose/{draft_id}", {"signature_html_override": "<p>Len pre túto správu</p>"}
    )
    assert r.status_code == 200, r.text
    marek = {"signature_person_id": str(people["marek"].id)}
    r = await client.send_json("PATCH", f"/api/mail/compose/{draft_id}", marek)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "signature_override_confirm"
    r = await client.send_json("PATCH", f"/api/mail/compose/{draft_id}", {**marek, "replace_signature_override": True})
    assert r.status_code == 200, r.text
    assert r.json()["signature_html_override"] is None
    assert "Marek Kováč" in _signature(r.json()["body_html"])
