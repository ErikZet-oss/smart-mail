"""Signature editor rules (DECISIONS D22, SETTINGS 03a / 11c)."""

from __future__ import annotations

import io
from email.message import EmailMessage

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.compose_models import Identity
from app.mail.models import Mailbox
from app.mail.sanitize import sanitize_html, sanitize_signature_html
from app.mail.signature import (
    SignatureError,
    apply_signature_languages,
    fill_variables,
    karta_template,
    text_template,
    unknown_variables,
)
from app.mail.signature_images import SignatureImageError, add_related_images, normalize_signature_image
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1, 1), (10, 20, 30)).save(out, format="PNG")
    return out.getvalue()


def test_d22_signature_keeps_table_style_and_https() -> None:
    html = (
        '<table style="border-collapse:collapse"><tr><td style="font-family:Arial">Peter Hudák</td></tr></table>'
        '<img src="https://example.com/signature-photo.png" alt="Peter Hudák">'
    )
    cleaned, gone = sanitize_signature_html(html)
    assert "<table" in cleaned
    assert "font-family" in cleaned or "Arial" in cleaned
    assert 'src="https://example.com/signature-photo.png"' in cleaned
    assert "data-sm-keep-src" in cleaned
    assert gone == []
    wrapped = sanitize_html(f'<div data-sm-signature="1">{cleaned}</div>')
    assert "https://example.com/signature-photo.png" in wrapped
    assert "about:blank#smartmail-remote" not in wrapped


def test_d22_signature_strips_script_and_reports_it() -> None:
    cleaned, gone = sanitize_signature_html("<p>Jana Nováková</p><script>alert(1)</script>")
    assert "script" not in cleaned.lower()
    assert "Jana Nováková" in cleaned
    assert any("script" in part for part in gone)


def test_d22_message_sanitizer_still_rewrites_remote_images() -> None:
    out = sanitize_html('<img src="https://tracker.example/pixel.gif" alt="x">')
    assert 'src="about:blank#smartmail-remote"' in out
    assert "data-remote-src" in out


def test_d22_empty_variable_drops_separator() -> None:
    assert fill_variables("{telefon} · {mobil}", {"telefon": "0900 000 000", "mobil": ""}) == "0900 000 000"
    assert fill_variables("Ahoj {meno} z {pobocka}", {"meno": "Jana", "pobocka": "Senica"}) == "Ahoj Jana z Senica"
    assert fill_variables("Ahoj {nespravne}", {}) == "Ahoj {nespravne}"


def test_d22_karta_template_uses_known_variables() -> None:
    html = karta_template("sk")
    assert "<table" in html
    assert "{meno}" in html and "{fotka}" in html and "{logo}" in html
    assert "S pozdravom" in html
    assert unknown_variables(html) == []
    assert "{mobil}" in text_template("cs")
    assert "S pozdravem" in text_template("cs")


def test_d22_unknown_variable_and_missing_sk() -> None:
    with pytest.raises(SignatureError) as unknown:
        apply_signature_languages({"sk": "<p>{nespravne}</p>"}, require_sk=True)
    assert unknown.value.code == "unknown_signature_variable"
    with pytest.raises(SignatureError) as missing:
        apply_signature_languages({"en": "<p>Hello</p>"}, require_sk=False)
    assert missing.value.code == "signature_sk_required"


def test_d22_image_limit_and_png() -> None:
    payload, content_type = normalize_signature_image(_png())
    assert content_type == "image/png"
    assert payload.startswith(b"\x89PNG")
    with pytest.raises(SignatureImageError) as too_big:
        normalize_signature_image(b"\x89PNG" + b"x" * (200 * 1024))
    assert too_big.value.code == "image_too_large"


def test_d22_related_cid_on_html_part() -> None:
    message = EmailMessage()
    message.set_content("text")
    message.add_alternative('<img src="cid:sig-1@smartmail" alt="">', subtype="html")
    add_related_images(message, [("sig-1@smartmail", _png(), "image/png")])
    cids = [part.get("Content-ID") for part in message.walk()]
    assert "<sig-1@smartmail>" in cids


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> Mailbox:
    account = await make_personal(db)
    mail_server.passwords[account.email] = PASSWORD
    assert (await client.login(account.email, PASSWORD)).status_code == 200
    return (await db.execute(select(Mailbox).where(Mailbox.email == account.email))).scalar_one()


@pytest.mark.asyncio
async def test_d22_identity_save_returns_stripped(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    identity = Identity(
        mailbox_id=mailbox.id,
        display_name="Jana Testová",
        email=mailbox.email,
        is_default=True,
        signature_html={},
    )
    db.add(identity)
    await db.commit()
    response = await client.send_json(
        "PUT",
        f"/api/settings/identities/{identity.id}",
        {
            "display_name": "Jana Testová",
            "email": mailbox.email,
            "signature_html": {"sk": "<p>Jana Testová</p><script>alert(1)</script>"},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "script" not in body["signature_html"]["sk"].lower()
    assert "Jana Testová" in body["signature_html"]["sk"]
    assert body["signature_stripped"]["sk"]


@pytest.mark.asyncio
async def test_d22_identity_image_upload(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    identity = Identity(
        mailbox_id=mailbox.id,
        display_name="Jana Testová",
        email=mailbox.email,
        is_default=True,
        signature_html={"sk": "<p>Jana</p>"},
    )
    db.add(identity)
    await db.commit()
    await client.csrf()
    response = await client.post(
        f"/api/settings/identities/{identity.id}/signature-images",
        files={"file": ("photo.png", _png(), "image/png")},
        headers={"X-CSRF-Token": client.cookies["sm_csrf"]},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["cid"].endswith("@smartmail")
    assert saved["preview_url"].startswith("/api/settings/signature-images/")
    assert "storage_key" not in saved
    fetched = await client.get(saved["preview_url"])
    assert fetched.status_code == 200
    assert fetched.content.startswith(b"\x89PNG")
