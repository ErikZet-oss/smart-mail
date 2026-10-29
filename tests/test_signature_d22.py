"""Signature editor rules (DECISIONS D22, SETTINGS 03a / 11c)."""

from __future__ import annotations

import io
import re
from email.message import EmailMessage

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.mail.compose_models import Identity
from app.mail.models import Mailbox
from app.mail.parse import parse_rfc822
from app.mail.remote_images import proxy_signature_images
from app.mail.sanitize import REMOTE_PLACEHOLDER, sanitize_compose_body, sanitize_html, sanitize_signature_html
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


def _sig_settings() -> Settings:
    return Settings(
        app_env="test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        storage_backend="local",
        mail_sync_enabled=False,
    )


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1, 1), (10, 20, 30)).save(out, format="PNG")
    return out.getvalue()


def test_d22_signature_keeps_table_style_and_https() -> None:
    html = (
        '<table style="border-collapse:collapse"><tr><td style="font-family:Arial">Peter Hudák</td></tr></table>'
        '<img src="https://example.com/signature-photo.png" alt="Peter Hudák" data-sm-keep-src="1">'
    )
    settings = _sig_settings()
    cleaned, gone = sanitize_signature_html(html, settings=settings)
    assert "<table" in cleaned
    assert "font-family" in cleaned or "Arial" in cleaned
    assert 'src="https://example.com/signature-photo.png"' in cleaned
    assert "data-sm-keep-src" in cleaned
    assert 'data-sm-keep-src="1"' not in cleaned
    assert gone == []
    wrapped = sanitize_html(f'<div data-sm-signature="1">{cleaned}</div>', settings=settings)
    assert "https://example.com/signature-photo.png" in wrapped
    assert "about:blank#smartmail-remote" not in wrapped
    shown = proxy_signature_images(wrapped, settings)
    assert "/api/mail/image-proxy?" in shown
    assert 'src="https://example.com/signature-photo.png"' not in shown


def test_d22_sent_signature_image_is_proxied_not_loaded_directly() -> None:
    settings = _sig_settings()
    signature, _gone = sanitize_signature_html(
        '<img src="https://cdn.example/logo.png" alt="Peter Hudák">',
        settings=settings,
    )
    message = EmailMessage()
    message.set_content("Ahoj")
    message.add_alternative(f'<div data-sm-signature="1">{signature}</div>', subtype="html")
    parsed = parse_rfc822(message.as_bytes(), settings)
    assert parsed.body_html_sanitized is not None
    assert "https://cdn.example/logo.png" in parsed.body_html_sanitized
    assert REMOTE_PLACEHOLDER not in parsed.body_html_sanitized
    shown = proxy_signature_images(parsed.body_html_sanitized, settings)
    assert "/api/mail/image-proxy?" in shown
    assert 'src="https://cdn.example/logo.png"' not in shown


def test_d22_received_keep_src_is_blocked_like_any_remote_image() -> None:
    out = sanitize_html(
        '<img src="https://evil.example/x.png" alt="x" data-sm-keep-src="1" data-cid="sig-1@smartmail">'
    )
    assert f'src="{REMOTE_PLACEHOLDER}"' in out
    assert 'data-remote-src="https://evil.example/x.png"' in out
    assert "data-sm-keep-src" not in out
    assert "data-cid" not in out
    assert re.search(r'(?<![\w-])src="https://', out) is None


def test_d22_compose_body_blocks_attacker_and_keeps_own_signature() -> None:
    settings = _sig_settings()
    signature, _gone = sanitize_signature_html(
        '<img src="https://cdn.example/logo.png" alt="Peter Hudák"><div>vnútro</div>',
        settings=settings,
    )
    body = (
        '<p>Ahoj</p><img src="https://evil.example/t.png" data-sm-keep-src="1">'
        f'<div data-sm-signature="1">{signature}</div>'
    )
    out = sanitize_compose_body(body, settings=settings)
    assert f'src="{REMOTE_PLACEHOLDER}"' in out
    assert "data-remote-src" in out and "evil.example" in out
    assert "https://cdn.example/logo.png" in out
    assert "data-sm-keep-src" in out
    assert 'data-sm-keep-src="1"' not in out
    assert "vnútro" in out


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
    assert "{meno}" in html and "{priezvisko}" in html and "{funkcia}" in html and "{pobocka}" in html
    assert "{mobil}" in html and "{email_pobocky}" in html and "{adresa_pobocky}" in html
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


def test_d22_svg_is_rejected() -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><image href="http://127.0.0.1/x"/></svg>'
    with pytest.raises(SignatureImageError) as rejected:
        normalize_signature_image(svg)
    assert rejected.value.code == "image_type"


def test_d22_image_pixel_dimensions_rejected() -> None:
    out = io.BytesIO()
    Image.new("RGB", (2001, 1), (1, 2, 3)).save(out, format="PNG")
    with pytest.raises(SignatureImageError) as too_wide:
        normalize_signature_image(out.getvalue())
    assert too_wide.value.code == "image_too_large"


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


def test_36_karta_is_the_customer_design_in_every_language() -> None:
    """Issue #36: logo | name, function · branch, phone/e-mail/address icons, e-shop button; tel: link kept."""
    from app.mail.signature import apply_signature_languages, fill_variables

    texts = {
        "sk": ("spojovací materiál", "Nakupujte v e-shope smartsro.sk"),
        "cs": ("spojovací materiál", "Nakupujte v e-shopu smartsro.sk"),
        "en": ("fasteners", "Shop online at smartsro.sk"),
        "de": ("Verbindungselemente", "Jetzt im Online-Shop smartsro.sk einkaufen"),
    }
    for lang, (tagline, button) in texts.items():
        html = karta_template(lang)
        assert tagline in html and button in html
        assert html.count("data:image/png;base64,") == 5  # logo, phone, e-mail, address, cart
        assert "utm_campaign=logo" in html and "utm_campaign=eshop" in html
        assert len(html.encode()) < 64 * 1024
        cleaned, stripped = apply_signature_languages({"sk": html}, require_sk=True)
        assert stripped == {}
        out = fill_variables(cleaned["sk"], {"meno": "Ján", "mobil": "+421 900 000 002", "email_pobocky": "a@b.sk"})
        assert 'href="tel:+421 900 000 002"' in out
        assert 'href="mailto:a@b.sk"' in out
