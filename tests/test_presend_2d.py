"""Phase 2d: the live „Kontrola pred odoslaním“ checks (W4a) and the W4b send gate."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.compose import language_check
from tests.conftest import Client, FakeMailServer
from tests.test_compose_1e import _signed_in

QUOTE = '<blockquote data-sm-quote="1"><p>V prílohe posielam objednávku.</p></blockquote>'
SIGNATURE = '<div data-sm-signature="1"><p>Jana Testová · cenník v PDF</p></div>'


async def _draft(client: Client, **patch: Any) -> dict[str, Any]:
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    draft_id = created.json()["id"]
    body = {"to_addrs": [{"email": "novak@abcstav.example"}], "subject": "Ponuka", **patch}
    r = await client.send_json("PATCH", f"/api/mail/compose/{draft_id}", body)
    assert r.status_code == 200, r.text
    return dict(r.json())


def _codes(draft: dict[str, Any]) -> dict[str, bool]:
    return {c["code"]: c["blocking"] for c in draft["checks"]}


async def test_2d_ai_placeholder_form_blocks_and_cannot_be_forced(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    draft = await _draft(client, body_html="<p>Cena je [[DOPLNIŤ: cena M8]] bez DPH.</p>")
    assert _codes(draft)["placeholder"] is True
    forced = await client.send_json("POST", f"/api/mail/compose/{draft['id']}/send", {"force": True})
    assert forced.status_code == 409 and forced.json()["detail"]["code"] == "pre_send_blocked"


async def test_2d_attachment_mention_counts_only_the_persons_own_text(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    quoted_only = await _draft(client, body_html=f"<p>Ďakujeme, potvrdzujeme.</p>{QUOTE}{SIGNATURE}")
    assert "attachment_mentioned" not in _codes(quoted_only)
    own = await _draft(client, body_html=f"<p>Cenník posielam v prílohe.</p>{QUOTE}{SIGNATURE}")
    assert _codes(own)["attachment_mentioned"] is False


async def test_2d_recipients_from_more_than_one_company_warn(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server)
    one = await _draft(client, body_html="<p>Dobrý deň</p>", cc_addrs=[{"email": "jana@abcstav.example"}])
    assert "multiple_companies" not in _codes(one)
    two = await _draft(client, body_html="<p>Dobrý deň</p>", cc_addrs=[{"email": "info@ina-firma.example"}])
    assert _codes(two)["multiple_companies"] is False
    assert "external_recipient" in _codes(two)


def test_2d_language_check() -> None:
    english = "Hello, thanks for your order, please find the invoice and delivery date below."
    slovak = "Dobrý deň, ďakujeme za objednávku, faktúru Vám pošleme zajtra spolu s tovarom."
    assert language_check(english, "sk") == {"code": "language_mismatch", "blocking": False, "message": "en:sk"}
    assert language_check(slovak, "sk") is None
    assert language_check(slovak, "cs") is None  # a Slovak reply to a Czech customer is normal
    assert language_check("Hello", "sk") is None  # too short to judge
    assert language_check(english, None) is None
