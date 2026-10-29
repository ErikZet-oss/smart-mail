"""Issue #28: compose keeps the signature card and the quoted HTML table.

The editor may flatten both. Send rebuilds the signature with render_signature
and the quote from the stored message.
"""

from __future__ import annotations

import re
import uuid
from email.message import EmailMessage
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail import storage
from app.mail.compose import build_mime, quote_html_for_message, quoted_image_parts
from app.mail.compose_html import assemble_outgoing_html, normalize_signature_html
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.models import Attachment, Mailbox, Message
from app.mail.sanitize import signature_span
from app.mail.signature import karta_template, preview_signature_html, render_signature
from app.mail.signature_images import add_related_images
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import NOW, PASSWORD, delta, env, snapshot
from tests.test_signature_d22 import _sig_settings

# 1×1 PNG. Fictional order logo, not a customer file.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
_HTTPS_LOGO = "https://cdn.example/order-logo.png"
_DISPLAY_QUOTE = (
    "<p>Objednávka</p>"
    '<img src="about:blank#smartmail-remote" '
    'data-remote-src="/api/mail/image-proxy?u=https%3A%2F%2Fcdn.example%2Forder-logo.png&amp;sig=x" alt="">'
    '<img src="cid:logo@order" alt="SMART">'
)


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
    assert "HACKED" not in html
    assert "evil.example" not in html
    assert "<table" in html
    assert "style=" in html
    assert "cid:logo@smartmail" in html
    assert "https://cdn.example/jana-testova.png" in html
    assert "Ďakujeme." in html
    assert "data-sm-" not in html
    assert "data-cid" not in html

    person_id = draft.signature_person_id or draft.person_id
    from app.auth.models import Person

    person = await db.get(Person, person_id) if person_id else None
    rendered = render_signature(person=person, branch=None, identity=identity, email=identity.email, language="sk")
    preview = preview_signature_html(person=person, branch=None, identity=identity, email=identity.email, language="sk")
    visible = re.sub(r'\sdata-sm-[\w-]*="[^"]*"', "", rendered)
    visible = re.sub(r"""\sdata-cid=(?:"[^"]*"|'[^']*')""", "", visible)
    assert normalize_signature_html(visible) in normalize_signature_html(html)
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


def _order_rfc822() -> bytes:
    html = (
        "<p>Objednávka</p>"
        f'<img src="{_HTTPS_LOGO}" alt="logo">'
        '<img src="cid:logo@order" alt="SMART">'
        "<table><tr><td>M10×30</td></tr></table>"
        "<script>alert(1)</script>"
    )
    message = EmailMessage()
    message["From"] = "Peter Hudec <peter@kovo.example>"
    message["Subject"] = "Objednávka"
    message.set_content("Objednávka")
    message.add_alternative(html, subtype="html")
    html_part = message.get_body(preferencelist=("html",))
    assert html_part is not None
    html_part.add_related(_PNG, maintype="image", subtype="png", cid="<logo@order>")
    return message.as_bytes()


def _related_payloads(message: EmailMessage) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for part in message.walk():
        cid = part.get("Content-ID")
        if not cid:
            continue
        payload = part.get_payload(decode=True)
        if isinstance(payload, bytes):
            found[str(cid).strip().strip("<>").lower()] = payload
    return found


def _mime_text(message: EmailMessage) -> str:
    """Decoded text parts plus the raw MIME, so a base64 body cannot hide a placeholder."""
    chunks = [message.as_string()]
    for part in message.walk():
        if part.get_content_maintype() != "text":
            continue
        content = part.get_content()
        if isinstance(content, str):
            chunks.append(content)
    return "\n".join(chunks)


def _local_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        storage_backend="local",
        storage_path=str(tmp_path),
        mail_sync_enabled=False,
    )


def test_issue28_quote_keeps_https_and_cid_not_the_display_placeholder(tmp_path: Path) -> None:
    """Outgoing quote uses raw HTML. Display placeholders never leave the building."""
    settings = _local_settings(tmp_path)
    raw_key, _sha = storage.put_bytes(settings, _order_rfc822(), prefix="mail/test/raw")
    logo_key, logo_sha = storage.put_bytes(settings, _PNG, prefix="mail/test/att")
    pdf_key, pdf_sha = storage.put_bytes(settings, b"%PDF-1.4 fictional", prefix="mail/test/att")
    source = Message(
        raw_storage_key=raw_key,
        body_html_sanitized=_DISPLAY_QUOTE,
        body_text="Objednávka",
    )
    quote = quote_html_for_message(settings, source)
    assert quote is not None
    assert _HTTPS_LOGO in quote
    assert "cid:logo@order" in quote
    assert "M10×30" in quote
    assert "about:blank" not in quote
    assert "/api/mail/image-proxy" not in quote
    assert "<script" not in quote.lower()

    logo = Attachment(
        message_id=uuid.uuid4(),
        filename="logo.png",
        content_type="image/png",
        storage_key=logo_key,
        sha256=logo_sha,
        content_id="logo@order",
        is_inline=True,
        av_status="clean",
    )
    pdf = Attachment(
        message_id=logo.message_id,
        filename="cennik-fiktivny.pdf",
        content_type="application/pdf",
        storage_key=pdf_key,
        sha256=pdf_sha,
        is_inline=False,
        av_status="clean",
    )
    for mode in ("reply", "forward"):
        html = assemble_outgoing_html(
            user_html="<p>Ďakujeme.</p>",
            quote_html=quote,
            signature_html=None,
            mode=mode,
            settings=settings,
        )
        blobs = quoted_image_parts(
            html,
            [logo, pdf],
            lambda key: storage.get_bytes(settings, key),
            skip_cids=set(),
        )
        assert [item[0] for item in blobs] == ["logo@order"]
        mime = EmailMessage()
        mime.set_content("Ďakujeme.")
        mime.add_alternative(html, subtype="html")
        add_related_images(mime, blobs)
        visible = _mime_text(mime)
        assert _HTTPS_LOGO in visible
        assert "about:blank" not in visible
        assert "/api/mail/image-proxy" not in visible
        assert "cennik-fiktivny.pdf" not in visible
        assert _related_payloads(mime).get("logo@order") == _PNG


@pytest.mark.asyncio
async def test_issue28_reply_and_forward_mime_keeps_https_and_cid_logo(
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
    raw_key, _sha = storage.put_bytes(settings, _order_rfc822(), prefix=f"mail/{mailbox.id}/raw")
    logo_key, logo_sha = storage.put_bytes(settings, _PNG, prefix=f"mail/{mailbox.id}/att")
    pdf_key, pdf_sha = storage.put_bytes(settings, b"%PDF-1.4 fictional", prefix=f"mail/{mailbox.id}/att")
    msg.raw_storage_key = raw_key
    msg.body_html_sanitized = _DISPLAY_QUOTE
    msg.body_text = "Objednávka"
    db.add(
        Attachment(
            message_id=msg.id,
            filename="logo.png",
            content_type="image/png",
            storage_key=logo_key,
            sha256=logo_sha,
            content_id="logo@order",
            is_inline=True,
            av_status="clean",
        )
    )
    db.add(
        Attachment(
            message_id=msg.id,
            filename="cennik-fiktivny.pdf",
            content_type="application/pdf",
            storage_key=pdf_key,
            sha256=pdf_sha,
            is_inline=False,
            av_status="clean",
        )
    )
    await db.commit()

    for mode in ("reply", "forward"):
        created = await client.send_json(
            "POST",
            "/api/mail/mailboxes/default/compose",
            {"mode": mode, "message_id": str(msg.id)},
        )
        assert created.status_code == 200, created.text
        draft_id = created.json()["id"]
        patched = await client.send_json(
            "PATCH",
            f"/api/mail/compose/{draft_id}",
            {
                "to_addrs": [{"email": "peter@kovo.example", "name": "Peter Hudec"}],
                "body_html": (
                    "<p>Ďakujeme.</p>"
                    '<blockquote data-sm-quote="1"><p>plochý text</p>'
                    '<img src="about:blank#smartmail-remote" '
                    'data-remote-src="/api/mail/image-proxy?u=x&amp;sig=y" alt=""></blockquote>'
                ),
            },
        )
        assert patched.status_code == 200, patched.text
        draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
        assert draft is not None
        await db.refresh(draft)
        identity = await db.get(Identity, draft.identity_id)
        assert identity is not None
        mime = await build_mime(db, settings, draft, identity)
        html = _html_part(mime)
        visible = _mime_text(mime)
        assert _HTTPS_LOGO in html
        assert "cid:logo@order" in html
        assert "M10×30" in html
        assert "about:blank" not in visible
        assert "/api/mail/image-proxy" not in visible
        assert "<script" not in html.lower()
        assert _related_payloads(mime).get("logo@order") == _PNG
        if mode == "forward":
            pdf = next(part for part in mime.walk() if part.get_filename() == "cennik-fiktivny.pdf")
            assert pdf.get_payload(decode=True) == b"%PDF-1.4 fictional"
            assert "Preposlaná správa" in html
        else:
            assert "cennik-fiktivny.pdf" not in visible
