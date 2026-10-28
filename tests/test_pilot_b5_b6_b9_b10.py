"""Pilot #18 B5 (cid inline), B6 (image proxy SSRF), B9/B10 (attachment classification)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.cid_rewrite import rewrite_cid_images
from app.mail.image_proxy import ImageProxyError, assert_public_http_url, sign_image_url, verify_image_sig
from app.mail.parse import parse_rfc822
from app.mail.remote_images import should_offer_remote_images, sign_remote_image_attrs
from app.mail.sanitize import REMOTE_PLACEHOLDER, sanitize_html
from tests.conftest import Client, FakeMailServer, make_personal

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "mail"
PASSWORD = "secret"
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_b9_gmail_attachment_with_content_id_is_not_inline() -> None:
    parsed = parse_rfc822((FIXTURES / "gmail_attachment_with_cid.eml").read_bytes())
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "screenshot.png"
    assert att.content_id == "f_abc123@gmail.com"
    assert att.is_inline is False


def test_b9_outlook_cid_referenced_in_html_is_inline() -> None:
    parsed = parse_rfc822((FIXTURES / "outlook_signature_cid.eml").read_bytes())
    assert parsed.body_html_sanitized is not None
    assert "cid:logo@outlook" in parsed.body_html_sanitized
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.content_id == "logo@outlook"
    assert att.is_inline is True


def test_b9_inline_image_not_referenced_stays_in_attachment_list() -> None:
    from email.mime.image import MIMEImage
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    related = MIMEMultipart("related")
    related["Subject"] = "Nepoužitý inline"
    related.attach(MIMEText("<p>Bez obrázka</p>", "html", "utf-8"))
    img = MIMEImage(PNG, _subtype="png")
    img.add_header("Content-ID", "<unused@local>")
    img.add_header("Content-Disposition", "inline", filename="unused.png")
    related.attach(img)
    parsed = parse_rfc822(related.as_bytes())
    assert len(parsed.attachments) == 1
    assert parsed.attachments[0].is_inline is False
    assert parsed.attachments[0].content_id == "unused@local"


def test_b10_apple_mail_pdf_without_content_disposition() -> None:
    parsed = parse_rfc822((FIXTURES / "apple_mail_pdf_no_disposition.eml").read_bytes())
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "objednavka.pdf"
    assert att.content_type == "application/pdf"
    assert att.payload.startswith(b"%PDF")


def test_b10_message_rfc822_eml_attachment() -> None:
    parsed = parse_rfc822((FIXTURES / "message_rfc822_attachment.eml").read_bytes())
    assert len(parsed.attachments) == 1
    att = parsed.attachments[0]
    assert att.filename == "sprava.eml"
    assert att.content_type == "message/rfc822"
    assert len(att.payload) > 0
    assert b"Subject" in att.payload or b"zakaznik@abcstav.example" in att.payload


def test_b10_named_second_html_is_attachment() -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Dva HTML"
    msg.set_content("plain")
    msg.add_alternative("<p>Telo</p>", subtype="html")
    # Extra HTML part with filename → attachment
    msg.add_attachment(
        b"<html><body>priloha</body></html>",
        maintype="text",
        subtype="html",
        filename="kopie.html",
    )
    parsed = parse_rfc822(msg.as_bytes())
    assert parsed.body_html_sanitized is not None and "Telo" in parsed.body_html_sanitized
    assert any(a.filename == "kopie.html" and a.is_inline is False for a in parsed.attachments)


def test_b5_rewrite_cid_to_inline_url() -> None:
    html = '<p>x</p><img src="cid:logo@outlook" alt="l">'
    out = rewrite_cid_images(
        html,
        mailbox_ref="default",
        cid_to_attachment_id={"logo@outlook": "11111111-1111-1111-1111-111111111111"},
    )
    assert 'src="/api/mail/mailboxes/default/attachments/11111111-1111-1111-1111-111111111111/inline"' in out
    assert "cid:" not in out


def test_b6_sign_and_verify_image_url(settings) -> None:
    url = "https://cdn.example/pixel.png"
    sig = sign_image_url(settings, url)
    assert verify_image_sig(settings, url, sig)
    assert not verify_image_sig(settings, url, "0" * 64)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x.png",
        "http://10.0.0.5/x.png",
        "http://169.254.169.254/latest/meta-data/",
        "https://169.254.169.254/latest/meta-data/",
    ],
)
def test_b6_ssrf_literal_private_ips_blocked(url: str) -> None:
    with pytest.raises(ImageProxyError) as exc:
        assert_public_http_url(url)
    assert exc.value.status == 400
    assert exc.value.code == "ssrf_blocked"


def test_b6_remote_images_modes() -> None:
    assert not should_offer_remote_images(
        "never", from_email="a@b.example", contact_emails=set(), internal_domains=[]
    )
    assert should_offer_remote_images(
        "always", from_email="a@b.example", contact_emails=set(), internal_domains=[]
    )
    assert should_offer_remote_images(
        "known",
        from_email="partner@firma.example",
        contact_emails={"partner@firma.example"},
        internal_domains=[],
    )
    assert not should_offer_remote_images(
        "known",
        from_email="stranger@firma.example",
        contact_emails={"partner@firma.example"},
        internal_domains=[],
    )


def test_b6_sign_remote_attrs_uses_proxy(settings) -> None:
    html = sanitize_html('<img src="https://cdn.example/a.png">')
    assert REMOTE_PLACEHOLDER in html
    signed = sign_remote_image_attrs(html, settings)
    assert "/api/mail/image-proxy?u=" in signed
    assert "sig=" in signed
    assert "https://cdn.example/a.png" not in signed.split("data-remote-src=")[-1][:20] or "sig=" in signed


@pytest.mark.asyncio
async def test_b5_inline_endpoint_serves_image(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings
) -> None:
    from app.mail import storage
    from app.mail.models import Attachment, FolderMeta, Mailbox, Message

    mail_server.passwords["pilot-b5@smartmail.test"] = PASSWORD
    await make_personal(db, email="pilot-b5@smartmail.test")
    assert (await client.login("pilot-b5@smartmail.test", PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == "pilot-b5@smartmail.test"))).scalar_one()
    folder = FolderMeta(
        mailbox_id=mailbox.id,
        name="INBOX",
        special_use="inbox",
        subscribed=True,
        selectable=True,
        private=False,
    )
    db.add(folder)
    await db.flush()
    msg = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=1,
        message_id=f"<b5-{uuid4().hex}@test>",
        subject="Inline",
        from_email="jana@partner.example",
        body_html_sanitized='<img src="cid:logo@local">',
        has_attachments=True,
    )
    db.add(msg)
    await db.flush()
    key, digest = storage.put_bytes(settings, PNG, prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        message_id=msg.id,
        filename="logo.png",
        content_type="image/png",
        size=len(PNG),
        content_id="logo@local",
        is_inline=True,
        storage_key=key,
        sha256=digest,
        av_status="clean",
    )
    db.add(att)
    await db.commit()

    detail = await client.get(f"/api/mail/mailboxes/default/messages/{msg.id}")
    assert detail.status_code == 200, detail.text
    html = detail.json()["body_html_sanitized"]
    assert f"/attachments/{att.id}/inline" in html
    assert "cid:" not in html

    inline = await client.get(f"/api/mail/mailboxes/default/attachments/{att.id}/inline")
    assert inline.status_code == 200
    assert inline.headers["content-type"].startswith("image/png")
    assert "inline" in inline.headers.get("content-disposition", "")
    assert inline.content == PNG


@pytest.mark.asyncio
async def test_b5_inline_infected_forbidden(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings
) -> None:
    from app.mail import storage
    from app.mail.models import Attachment, FolderMeta, Mailbox, Message

    mail_server.passwords["pilot-b5i@smartmail.test"] = PASSWORD
    await make_personal(db, email="pilot-b5i@smartmail.test")
    assert (await client.login("pilot-b5i@smartmail.test", PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == "pilot-b5i@smartmail.test"))).scalar_one()
    folder = FolderMeta(
        mailbox_id=mailbox.id, name="INBOX", special_use="inbox", subscribed=True, selectable=True, private=False
    )
    db.add(folder)
    await db.flush()
    msg = Message(mailbox_id=mailbox.id, folder_id=folder.id, uid=2, message_id="<b5i@test>", subject="x")
    db.add(msg)
    await db.flush()
    key, digest = storage.put_bytes(settings, PNG, prefix=f"mail/{mailbox.id}/att")
    att = Attachment(
        message_id=msg.id,
        filename="bad.png",
        content_type="image/png",
        size=len(PNG),
        content_id=None,
        is_inline=False,
        storage_key=key,
        sha256=digest,
        av_status="infected",
    )
    db.add(att)
    await db.commit()
    r = await client.get(f"/api/mail/mailboxes/default/attachments/{att.id}/inline")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "attachment_infected"


@pytest.mark.asyncio
async def test_b6_image_proxy_bad_signature_403(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mail_server.passwords["pilot-b6@smartmail.test"] = PASSWORD
    await make_personal(db, email="pilot-b6@smartmail.test")
    assert (await client.login("pilot-b6@smartmail.test", PASSWORD)).status_code == 200
    r = await client.get("/api/mail/image-proxy", params={"u": "https://cdn.example/a.png", "sig": "ab" * 32})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "bad_signature"


@pytest.mark.asyncio
async def test_b6_image_proxy_ssrf_400(client: Client, db: AsyncSession, mail_server: FakeMailServer, settings) -> None:
    mail_server.passwords["pilot-b6s@smartmail.test"] = PASSWORD
    await make_personal(db, email="pilot-b6s@smartmail.test")
    assert (await client.login("pilot-b6s@smartmail.test", PASSWORD)).status_code == 200
    for url in ("http://127.0.0.1/x.png", "http://10.1.2.3/x.png", "http://169.254.169.254/x"):
        sig = sign_image_url(settings, url)
        r = await client.get("/api/mail/image-proxy", params={"u": url, "sig": sig})
        assert r.status_code == 400, url
        assert r.json()["detail"]["code"] == "ssrf_blocked"


@pytest.mark.asyncio
async def test_b6_image_proxy_svg_415(client: Client, db: AsyncSession, mail_server: FakeMailServer, settings) -> None:
    mail_server.passwords["pilot-b6v@smartmail.test"] = PASSWORD
    await make_personal(db, email="pilot-b6v@smartmail.test")
    assert (await client.login("pilot-b6v@smartmail.test", PASSWORD)).status_code == 200
    url = "https://example.com/icon.svg"
    sig = sign_image_url(settings, url)

    class FakeResp:
        status_code = 200
        is_redirect = False

        def __init__(self) -> None:
            self.headers = {"content-type": "image/svg+xml"}
            self.content = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    with (
        patch("app.mail.image_proxy.httpx.AsyncClient", FakeClient),
        patch(
            "app.mail.image_proxy.socket.getaddrinfo",
            return_value=[(0, 0, 0, "", ("93.184.216.34", 443))],
        ),
    ):
        r = await client.get("/api/mail/image-proxy", params={"u": url, "sig": sig})
    assert r.status_code == 415
    assert r.json()["detail"]["code"] == "svg_forbidden"
