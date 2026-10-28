"""Issue #31: sent mail carries signature images Gmail can show.

A „Karta“ pasted from Roundcube keeps its table and colours. The logo, a
``data:`` PNG icon and an uploaded icon are related parts. One ``https://``
image stays a URL. Nothing in the MIME uses a relative, ``data:`` or ``about:`` src.
"""

from __future__ import annotations

import base64
import io
import re
import uuid
from email.message import EmailMessage
from pathlib import Path

import pytest
import structlog
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import configure_logging
from app.mail import storage
from app.mail.compose import build_mime, log_stripped_images
from app.mail.compose_html import assemble_outgoing_html
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.models import Mailbox
from app.mail.outgoing_images import normalize_outgoing_images
from app.mail.sanitize import sanitize_signature_html
from app.mail.signature import LOGO_CID
from app.mail.signature_images import add_related_images
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD
from tests.test_signature_d22 import _sig_settings

_FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "issue31_outgoing_signature.html"
# 1×1 PNG. Fictional icon, not a customer file.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)
_PNG_B64 = base64.b64encode(_PNG).decode("ascii")
_ICON_CID = "img-ebf4f635a17d10d6@smartmail"
_UPLOAD_ID = "phone-fiktivne"
_UPLOAD_CID = "sig-phone@smartmail"
_HTTPS = "https://cdn.example/jana-testova.png"
_BAD_SRC = re.compile(r"""src\s*=\s*["'](?:/|data:|about:)""", re.IGNORECASE)

_CARD = (
    '<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;border-left:3px solid #C6CEDA;'
    'font-family:Arial,sans-serif"><tr><td style="padding:10px 14px;vertical-align:middle">'
    '<img src="cid:logo@smartmail" alt="SMART" width="96" height="33" style="display:block"></td>'
    '<td style="padding:10px 8px;vertical-align:middle">'
    '<div style="font-weight:700;font-size:14px;color:#1B2430">Jana Testová</div>'
    '<div style="color:#0F75BC;font-size:13px">obchod</div>'
    f'<div style="font-size:12px;color:#5B6576"><img src="data:image/png;base64,{_PNG_B64}" alt="" '
    'width="14" height="14"> +421 900 000 000</div>'
    f'<div style="font-size:12px;color:#5B6576"><img src="{_HTTPS}" alt="Jana Testová" width="16" height="16"> '
    "jana.testova@smartsro.example</div></td>"
    '<td style="padding:10px 14px">'
    f'<img src="/api/settings/signature-images/{_UPLOAD_ID}" alt="" width="16" height="16">'
    "</td></tr></table>"
)


def _logo_png() -> bytes:
    path = Path(__file__).resolve().parents[1] / "design" / "brand" / "logo-smart.png"
    data = path.read_bytes()
    assert data.startswith(b"\x89PNG")
    assert b"<svg" not in data.lower()
    return data


def _upload_png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1, 1), (15, 117, 188)).save(out, format="PNG")
    return out.getvalue()


def _related(message: EmailMessage) -> list[tuple[str, str, bytes]]:
    found: list[tuple[str, str, bytes]] = []
    for part in message.walk():
        cid = part.get("Content-ID")
        if not cid or part.get_content_maintype() != "image":
            continue
        payload = part.get_payload(decode=True)
        assert isinstance(payload, bytes)
        found.append((cid.strip("<>"), part.get_content_type() or "", payload))
    return found


def _mime_from(html: str, blobs: list[tuple[str, bytes, str]]) -> EmailMessage:
    message = EmailMessage()
    message.set_content("Jana Testová")
    message.add_alternative(html, subtype="html")
    add_related_images(message, blobs)
    return message


def test_issue31_karta_snapshot_has_three_related_parts_and_one_https() -> None:
    """Pasted Karta: logo CID, data PNG, uploaded icon, one https URL."""
    logo = _logo_png()
    upload = _upload_png()
    settings = _sig_settings()
    stamped, gone = sanitize_signature_html(_CARD, settings)
    assert gone == []
    wrapped = f'<div data-sm-signature="1">{stamped}</div>'
    html, blobs, stripped = normalize_outgoing_images(
        wrapped,
        logo_png=logo,
        images_by_id={_UPLOAD_ID: (_UPLOAD_CID, upload, "image/png")},
    )
    assert stripped == 0
    expected = _FIXTURE.read_text(encoding="utf-8").strip()
    assert expected in html
    assert "data-sm-" not in html
    assert "data-cid" not in html
    assert _HTTPS in html
    assert _BAD_SRC.search(html) is None
    assert "http://" not in html
    assert "<table" in html
    assert "#0F75BC" in html
    assert "#1B2430" in html
    assert "Jana Testová" in html

    assert [(cid, ctype) for cid, ctype, _data in ((b[0], b[2], b[1]) for b in blobs)] == [
        (LOGO_CID, "image/png"),
        (_ICON_CID, "image/png"),
        (_UPLOAD_CID, "image/png"),
    ]
    assert blobs[0][1] == logo
    assert blobs[1][1] == _PNG
    assert blobs[2][1] == upload

    mime = _mime_from(html, blobs)
    body = mime.get_body(preferencelist=("html",))
    assert body is not None
    assert body.get_content().strip() == html
    related = _related(mime)
    assert len(related) == 3
    assert [item[0] for item in related] == [LOGO_CID, _ICON_CID, _UPLOAD_CID]
    assert {item[1] for item in related} == {"image/png"}
    raw = mime.as_bytes().lower()
    assert b"image/svg" not in raw
    assert b"<svg" not in raw
    assert b"data:image" not in raw


def test_issue31_keep_src_attribute_before_src() -> None:
    """``data-sm-keep-src`` and ``data-src`` before ``src`` are not the image URL."""
    logo = _logo_png()
    data_uri = f"data:image/png;base64,{_PNG_B64}"
    proxy = "/api/mail/image-proxy?u=https%3A%2F%2Fcdn.example%2Fjana-testova.png"
    html = (
        '<img data-sm-keep-src="not-the-src" data-src="x" src="/logo-smart.svg" alt="SMART">'
        f'<img data-sm-keep-src="not-the-src" data-src="x" src="{data_uri}" alt="">'
        f'<img data-sm-keep-src="not-the-src" data-src="x" src="{proxy}" alt="">'
    )
    out, blobs, stripped = normalize_outgoing_images(html, logo_png=logo)
    assert stripped == 0
    assert 'src="cid:logo@smartmail"' in out
    assert f'src="cid:{_ICON_CID}"' in out
    assert 'src="https://cdn.example/jana-testova.png"' in out
    assert "/logo-smart" not in out
    assert "data:image" not in out
    assert "image-proxy" not in out
    assert "not-the-src" not in out
    assert out.count('data-src="x"') == 3
    assert "data-sm-" not in out
    assert [(cid, data) for cid, data, _ctype in blobs] == [(LOGO_CID, logo), (_ICON_CID, _PNG)]


def test_issue31_mime_drops_internal_attributes_and_srcset() -> None:
    token = "38daf9db0b3964af75a401243133d3a5ceee295a700c8df552e35c619843799b"
    html = (
        '<div data-sm-signature="1" data-cid="wrap">'
        f'<img src="{_HTTPS}" alt="Jana Testová" data-sm-keep-src="{token}" '
        'data-cid="sig-1@smartmail" data-sm-extra="1" '
        f'srcset="/logo-smart.svg 1x, data:image/png;base64,{_PNG_B64} 2x">'
        "</div>"
        '<blockquote data-sm-quote="1"><p>Ahoj</p></blockquote>'
    )
    out, blobs, stripped = normalize_outgoing_images(html, logo_png=_logo_png())
    assert stripped == 0
    assert blobs == []
    assert f'src="{_HTTPS}"' in out
    assert "data-sm-" not in out
    assert "data-cid" not in out
    assert "srcset" not in out.lower()
    assert token not in out
    assert "/logo-smart" not in out
    assert "data:" not in out
    assert "<div>" in out
    assert "Ahoj" in out


def test_issue31_unquoted_or_bare_src_is_cleared() -> None:
    html = '<img src=/logo-smart.svg alt="SMART"><img src alt=""><img src= alt=""><img src="" alt="">'
    out, blobs, stripped = normalize_outgoing_images(html, logo_png=_logo_png())
    assert stripped == 4
    assert blobs == []
    assert out.count('src=""') == 4
    assert "/logo-smart" not in out
    assert "data:" not in out


def test_issue31_logo_svg_path_is_sent_as_png() -> None:
    logo = _logo_png()
    html, blobs, stripped = normalize_outgoing_images(
        '<p style="color:#0F75BC"><img src="/logo-smart.svg" alt="SMART" width="96" height="33"></p>',
        logo_png=logo,
    )
    assert stripped == 0
    assert 'src="cid:logo@smartmail"' in html
    assert "/logo-smart" not in html
    assert blobs == [(LOGO_CID, logo, "image/png")]
    raw = _mime_from(html, blobs).as_bytes().lower()
    assert b"image/svg" not in raw
    assert b"<svg" not in raw


def test_issue31_proxy_url_becomes_https_and_junk_is_counted_not_logged() -> None:
    secret = "http://tajne.example/icon.png"
    html = (
        '<img src="/api/mail/image-proxy?u=https%3A%2F%2Fcdn.example%2Fjana-testova.png&amp;sig=abc" alt="">'
        f'<img src="{secret}" alt="x">'
        '<img src="about:blank#smartmail-remote" alt="">'
        '<img src="" alt="">'
        '<img src="data:image/svg+xml;base64,PHN2Zy8+" alt="">'
    )
    out, blobs, stripped = normalize_outgoing_images(html, logo_png=None)
    assert blobs == []
    assert stripped == 4
    assert 'src="https://cdn.example/jana-testova.png"' in out
    assert "image-proxy" not in out
    assert "tajne.example" not in out
    assert "about:" not in out
    assert "data:" not in out
    assert _BAD_SRC.search(out) is None
    # A second configure replaces the processor list. A logger cached on first use
    # keeps the old JSON chain and capture_logs stays empty.
    configure_logging("INFO")
    log_stripped_images("warmup", 1)
    configure_logging("INFO")
    with structlog.testing.capture_logs() as logs:
        log_stripped_images("draft-1", stripped)
    assert logs == [{"count": 4, "draft_id": "draft-1", "event": "compose.images_stripped", "log_level": "info"}]
    assert "tajne.example" not in repr(logs)
    assert "http" not in repr(logs)


@pytest.mark.parametrize(
    ("kind", "payload", "content_type"),
    [
        ("gif", b"GIF89a" + b"\x01\x00\x01\x00" + b"\x00" * 8, "image/gif"),
        ("webp", b"RIFF\x18\x00\x00\x00WEBPVP8 " + b"\x00" * 8, "image/webp"),
        ("jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 8, "image/jpeg"),
    ],
)
def test_issue31_raster_data_uris_become_cid(kind: str, payload: bytes, content_type: str) -> None:
    src = "data:image/" + kind + ";base64," + base64.b64encode(payload).decode("ascii")
    html, blobs, stripped = normalize_outgoing_images(f'<img src="{src}" alt="">', logo_png=None)
    assert stripped == 0
    assert len(blobs) == 1
    assert blobs[0][1] == payload
    assert blobs[0][2] == content_type
    assert html.startswith('<img src="cid:img-')
    assert "data:" not in html


def test_issue31_png_label_on_svg_bytes_is_dropped() -> None:
    payload = base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>').decode("ascii")
    html, blobs, stripped = normalize_outgoing_images(
        f'<img src="data:image/png;base64,{payload}" alt="">',
        logo_png=None,
    )
    assert stripped == 1
    assert blobs == []
    assert "data:" not in html
    assert 'src=""' in html


def test_issue31_assemble_then_normalize_matches_the_snapshot() -> None:
    """The send path wraps the signature, then rewrites images. Layout stays."""
    logo = _logo_png()
    upload = _upload_png()
    settings = _sig_settings()
    stamped, _gone = sanitize_signature_html(_CARD, settings)
    html = assemble_outgoing_html(
        user_html="<p>Ďakujeme.</p>",
        quote_html=None,
        signature_html=stamped,
        mode="new",
        settings=settings,
    )
    out, blobs, stripped = normalize_outgoing_images(
        html,
        logo_png=logo,
        images_by_id={_UPLOAD_ID: (_UPLOAD_CID, upload, "image/png")},
    )
    assert stripped == 0
    assert "Ďakujeme." in out
    assert _FIXTURE.read_text(encoding="utf-8").strip() in out
    assert "data-sm-" not in out
    assert "data-cid" not in out
    assert len(blobs) == 3


@pytest.mark.asyncio
async def test_issue31_build_mime_sends_the_karta_images(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    account = await make_personal(db)
    mail_server.passwords[account.email] = PASSWORD
    assert (await client.login(account.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == account.email))).scalar_one()
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    logo = _logo_png()
    upload = _upload_png()
    key, _digest = storage.put_bytes(settings, upload, prefix="signatures")
    identity = (
        await db.execute(select(Identity).where(Identity.mailbox_id == mailbox.id, Identity.is_default.is_(True)))
    ).scalar_one()
    identity.signature_html = {"sk": _CARD}
    identity.signature_images = [
        {
            "id": _UPLOAD_ID,
            "cid": _UPLOAD_CID,
            "storage_key": key,
            "content_type": "image/png",
            "size": len(upload),
            "filename": "telefon.png",
        }
    ]
    await db.commit()

    draft = await db.get(ComposeDraft, uuid.UUID(draft_id))
    assert draft is not None
    await db.refresh(draft)
    await db.refresh(identity)
    mime = await build_mime(db, settings, draft, identity)
    body = mime.get_body(preferencelist=("html",))
    assert body is not None
    html = body.get_content()
    assert isinstance(html, str)
    assert _FIXTURE.read_text(encoding="utf-8").strip() in html
    assert "data-sm-" not in html
    assert "data-cid" not in html
    assert _HTTPS in html
    assert _BAD_SRC.search(html) is None
    assert "data:image" not in html
    related = _related(mime)
    assert [item[0] for item in related] == [LOGO_CID, _ICON_CID, _UPLOAD_CID]
    assert related[0][1:] == ("image/png", logo)
    assert related[1][1:] == ("image/png", _PNG)
    assert related[2][1:] == ("image/png", upload)
    raw = mime.as_bytes().lower()
    assert b"image/svg" not in raw
    assert b"<svg" not in raw
