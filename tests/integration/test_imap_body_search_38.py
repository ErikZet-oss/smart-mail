"""Issue #38 against the local test IMAP server (Dovecot, fictional mail only): a word that occurs only in the body of
a message that was never opened is found through the server search; without `server=true` it is not.

Runs when TEST_IMAP_HOST is set (see tests/integration/test_imap_messages_1d.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from imapclient import IMAPClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.mail.models import Message
from tests.conftest import Client, make_personal
from tests.integration.test_imap_messages_1d import (  # noqa: F401  (fixtures)
    DOMAIN,
    addr,
    imap,
    login,
    mail_server,
    pytestmark,
    refresh,
    reseed_senica,
    settings,
)


def _unopened_mail() -> bytes:
    msg = EmailMessage()
    msg["From"] = "Eva Testovacia <eva@dodavatel.example>"
    msg["To"] = addr("senica")
    msg["Subject"] = "Fiktívna zásielka 38"
    msg["Date"] = format_datetime(datetime(2026, 10, 28, 9, 0, tzinfo=UTC))
    msg["Message-ID"] = make_msgid(domain="dodavatel.example")
    msg.set_content("Dobrý deň,\n\nv zásielke je aj paletovy-kod-ZX38 podľa dohody.\n")
    return msg.as_bytes()


async def test_38_body_word_of_an_unopened_message_is_found_on_the_server(
    client: Client,
    db: AsyncSession,
    imap: IMAPClient,  # noqa: F811  (fixture imported from the 1d module)
) -> None:
    await make_personal(db, email=addr("senica"))
    await login(client, "senica")
    imap.append("INBOX", _unopened_mail())
    await refresh(client)

    stored = (await db.execute(select(Message).where(Message.subject == "Fiktívna zásielka 38"))).scalar_one()
    assert stored.body_text is None  # never opened: the body is not in the local index

    params = {"q": "paletovy-kod-ZX38", "fields": "body", "scope": "all"}
    local = await client.get("/api/search", params=params)
    assert local.status_code == 200, local.text
    assert local.json()["messages"] == []

    both = await client.get("/api/search", params={**params, "server": "true"})
    assert both.status_code == 200, both.text
    assert both.json()["server_search"] == "ok"
    assert [m["subject"] for m in both.json()["messages"]] == ["Fiktívna zásielka 38"]
    assert DOMAIN in addr("senica")
