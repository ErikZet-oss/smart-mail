"""Issue #28: compose keeps the signature card and the quoted HTML table.

The editor may flatten both. Send rebuilds the signature with render_signature
and the quote from the stored message.
"""

from __future__ import annotations

import uuid
from email.message import EmailMessage

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.compose import build_mime
from app.mail.compose_html import assemble_outgoing_html, normalize_signature_html
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.models import Mailbox, Message
from app.mail.sanitize import signature_span
from app.mail.signature import karta_template, preview_signature_html, render_signature
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import NOW, PASSWORD, delta, env, snapshot
from tests.test_signature_d22 import _sig_settings


def test_issue28_assemble_ignores_editor_signature_and_quote() -> None:
    settings = _sig_settings()
    user = (
        "<p>Ďakujeme.</p>"
        '<blockquote data-sm-quote="1"><p>plochý text</p></blockquote>'
        '<div data-sm-signature="1"><p>HACKED</p></div>'
    )
    signature = (
        '<table style="border-collapse:collapse"><tr><td style="color:#0f75bc">Jana Testová</td></tr></table>'
        '<img src="cid:logo@smartmail" alt="SMART">'
        '<img src="https://cdn.example/jana.png" alt="Jana Testová">'
    )
    quote = '<table style="border-collapse:collapse"><tr><td>M10×30</td><td>5 000 ks</td></tr></table>'
    out = assemble_outgoing_html(
        user_html=user,
        quote_html=quote,
        signature_html=signature,
        mode="reply",
        settings=settings,
    )
    assert "HACKED" not in out
    assert "plochý text" not in out
    assert "Ďakujeme." in out
    assert "M10×30" in out
    assert "<table" in out
    span = signature_span(out)
    assert span is not None
    assert "https://cdn.example/jana.png" in span[1]
    assert "cid:logo@smartmail" in span[1]
    again = assemble_outgoing_html(
        user_html=out,
        quote_html=quote,
        signature_html=signature,
        mode="reply",
        settings=settings,
    )
    assert normalize_signature_html(again) == normalize_signature_html(out)


def test_issue28_forward_note_is_inside_the_quote() -> None:
    out = assemble_outgoing_html(
        user_html="<p>Preposielam</p>",
        quote_html="<table><tr><td>Cenník</td></tr></table>",
        signature_html=None,
        mode="forward",
        settings=_sig_settings(),
    )
    assert out.count("Preposlaná správa") == 1
    assert "Cenník" in out
    again = assemble_outgoing_html(
        user_html=out,
        quote_html="<table><tr><td>Cenník</td></tr></table>",
        signature_html=None,
        mode="forward",
        settings=_sig_settings(),
    )
    assert again.count("Preposlaná správa") == 1


def _html_part(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("html",))
    assert part is not None
    content = part.get_content()
    assert isinstance(content, str)
    return content


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Mailbox:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()


@pytest.mark.asyncio
async def test_issue28_send_signature_matches_preview_not_flattened_editor(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    """Karta with a table, inline styles, a CID logo and an https image survives send."""
    mailbox = await _signed_in(client, db, mail_server)
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    identity = (
        await db.execute(select(Identity).where(Identity.mailbox_id == mailbox.id, Identity.is_default.is_(True)))
    ).scalar_one()
    template = karta_template("sk") + '<img src="https://cdn.example/jana-testova.png" alt="Jana Testová">'
    identity.signature_html = {"sk": template}
    await db.commit()

    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "peter@kovo.example", "name": "Peter Hudec"}],
            "subject": "Ponuka",
            "body_html": (
                "<p>Ďakujeme.</p>"
                "<p>Jana Testová obchod</p>"
                '<div data-sm-signature="1"><p>HACKED</p><img src="https://evil.example/x.png" alt="x"></div>'
            ),
        },
    )
    assert patched.status_code == 200, patched.text
    assert "HACKED" not in patched.json()["body_html"]

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    await db.refresh(draft)
    await db.refresh(identity)
    mime = await build_mime(db, settings, draft, identity)
    html = _html_part(mime)
    span = signature_span(html)
    assert span is not None
    inner = span[1]
    assert "HACKED" not in html
    assert "evil.example" not in html
    assert "<table" in inner
    assert "style=" in inner
    assert "cid:logo@smartmail" in inner
    assert "https://cdn.example/jana-testova.png" in inner
    assert "Ďakujeme." in html

    person_id = draft.signature_person_id or draft.person_id
    from app.auth.models import Person

    person = await db.get(Person, person_id) if person_id else None
    rendered = render_signature(person=person, branch=None, identity=identity, email=identity.email, language="sk")
    preview = preview_signature_html(person=person, branch=None, identity=identity, email=identity.email, language="sk")
    assert normalize_signature_html(inner) == normalize_signature_html(rendered)
    assert normalize_signature_html(preview) == normalize_signature_html(rendered)


@pytest.mark.asyncio
async def test_issue28_reply_quote_keeps_the_original_table(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    from app.mail.sync import apply_snapshot

    snap = snapshot(
        delta("INBOX", 1, 2, 1, 1, new=[env(1, subject="Objednávka")], present_uids={1}),
        folders=("INBOX", "Drafts", "Sent"),
    )
    await apply_snapshot(db, mailbox, snap, now=NOW)
    await db.commit()
    msg = (await db.execute(select(Message).where(Message.mailbox_id == mailbox.id))).scalar_one()
    table = '<table style="border-collapse:collapse"><tr><td>M10×30</td><td>5 000 ks</td></tr></table>'
    msg.body_html_sanitized = table
    msg.body_text = "M10×30 5 000 ks"
    await db.commit()

    created = await client.send_json(
        "POST",
        "/api/mail/mailboxes/default/compose",
        {"mode": "reply", "message_id": str(msg.id)},
    )
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    patched = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "body_html": "<p>Ďakujeme.</p><p>M10×30 5 000 ks</p>",
        },
    )
    assert patched.status_code == 200, patched.text

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    await db.refresh(draft)
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    html = _html_part(await build_mime(db, settings, draft, identity))
    assert "<blockquote" in html
    assert "M10×30" in html
    assert "<td>5 000 ks</td>" in html or "5 000 ks" in html
    quote_at = html.lower().find("<blockquote")
    table_at = html.lower().find("<table")
    assert quote_at != -1 and table_at > quote_at
    assert "Ďakujeme." in html[:quote_at]
