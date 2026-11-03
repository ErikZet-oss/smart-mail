"""#203 W4g / M4b Adresár – výber príjemcov: read-only sources (recent, branches, Money cache). Fictional data only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Person, Role
from app.core.config import Settings
from app.mail.compose_models import ComposeDraft
from app.mail.models import Mailbox
from app.money.models import MoneyCompany, MoneyPerson
from tests.conftest import Client, FakeMailServer
from tests.test_mail_sync_1c import _signed_in

NOW = datetime.now(UTC)


async def _person_id(client: Client) -> uuid.UUID:
    return uuid.UUID((await client.get("/api/auth/me")).json()["person"]["id"])


def _draft(
    mailbox: Mailbox, person: uuid.UUID | None, status: str, to: list[str], cc: tuple[str, ...] = ()
) -> ComposeDraft:
    return ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=mailbox.credential_account_id,
        person_id=person,
        status=status,
        to_addrs=[{"email": e, "name": e.split("@")[0].title()} for e in to],
        cc_addrs=[{"email": e} for e in cc],
    )


async def test_203_recent_only_active_person_sent_deduplicated_newest_first(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    me = await _person_id(client)
    other = Person(first_name="Iná", last_name="Osoba", role=Role.sales, active=True)
    db.add(other)
    await db.flush()
    old = _draft(mailbox, me, "sent", ["stary@firma1.example"])
    first = _draft(mailbox, me, "sent", ["novak@firma1.example"], cc=("kopia@firma2.example",))
    newest = _draft(mailbox, me, "sent", ["NOVAK@firma1.example", "druhy@firma3.example"])
    db.add_all(
        [
            old,
            first,
            newest,
            _draft(mailbox, me, "editing", ["koncept@firma4.example"]),  # not sent
            _draft(mailbox, other.id, "sent", ["cudzi@firma5.example"]),  # another person
        ]
    )
    await db.flush()
    for d, age in ((old, 120), (first, 5), (newest, 1)):
        await db.execute(
            update(ComposeDraft).where(ComposeDraft.id == d.id).values(updated_at=NOW - timedelta(days=age))
        )
    await db.commit()
    rows = (await client.get("/api/contacts/picker/recent")).json()
    assert [r["key"] for r in rows] == [
        "novak@firma1.example",
        "druhy@firma3.example",
        "kopia@firma2.example",
    ]  # 90-day window, no duplicates (case-insensitive), other persons and drafts left out
    summary = (await client.get("/api/contacts/picker/summary")).json()
    assert summary["recent"] == 3


async def test_203_recent_is_capped_at_50(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    me = await _person_id(client)
    db.add(_draft(mailbox, me, "sent", [f"p{i}@firma.example" for i in range(70)]))
    await db.commit()
    assert len((await client.get("/api/contacts/picker/recent")).json()) == 50


async def test_203_branches_are_the_branch_mailboxes(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    mailbox = await _signed_in(client, db, mail_server)
    db.add_all([Branch(name="Pobočka Nitra", mailbox_id=mailbox.id), Branch(name="Bez schránky")])
    await db.commit()
    rows = (await client.get("/api/contacts/picker/branches")).json()
    assert [(r["name"], r["email"]) for r in rows] == [("Pobočka Nitra", mailbox.email)]


async def test_203_money_needs_a_search_skips_inactive_and_rows_without_email(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    await _signed_in(client, db, mail_server, role=Role.viewer)  # viewer may read
    company = uuid.uuid4()
    db.add_all(
        [
            MoneyCompany(
                money_id=company,
                name="Fiktívna Stavba s.r.o.",
                ico="11111111",
                email="info@stavba.example",
                emails=["info@stavba.example", "faktury@stavba.example"],
                connections=[],
                active=True,
                synced_at=NOW,
            ),
            MoneyCompany(
                money_id=uuid.uuid4(), name="Stavba bez mailu", emails=[], connections=[], active=True, synced_at=NOW
            ),
            MoneyCompany(
                money_id=uuid.uuid4(),
                name="Stavba zmazaná",
                email="zmazana@stavba.example",
                emails=[],
                connections=[],
                active=False,
                synced_at=NOW,
            ),
            MoneyPerson(
                money_id=uuid.uuid4(),
                company_money_id=company,
                first_name="Ján",
                last_name="Stavbár",
                email="jan@stavba.example",
                active=True,
                synced_at=NOW,
            ),
            MoneyPerson(money_id=uuid.uuid4(), first_name="Bez", last_name="Mailu", active=True, synced_at=NOW),
        ]
    )
    await db.commit()
    assert (await client.get("/api/contacts/picker/money", params={"q": "s"})).status_code == 422
    assert (await client.get("/api/contacts/picker/money")).status_code == 422
    page = (await client.get("/api/contacts/picker/money", params={"q": "stavb"})).json()
    assert page["total"] == 3
    assert {(r["email"], r["organization"]) for r in page["items"]} == {
        ("info@stavba.example", "Fiktívna Stavba s.r.o."),
        ("faktury@stavba.example", "Fiktívna Stavba s.r.o."),
        ("jan@stavba.example", "Fiktívna Stavba s.r.o."),
    }
    assert (await client.get("/api/contacts/picker/summary")).json()["money"] == 3


async def test_203_bcc_reaches_the_smtp_envelope_and_the_send_guard(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    """Skrytá kópia was stored but never sent; now it is a Bcc header (aiosmtplib strips it before transmission)."""
    from app.mail.compose import build_mime
    from app.mail.compose_models import Identity
    from app.mail.send_guard import collect_recipients

    await _signed_in(client, db, mail_server)
    created = await client.send_json("POST", "/api/mail/mailboxes/default/compose", {"mode": "new"})
    assert created.status_code == 200, created.text
    draft_id = created.json()["id"]
    saved = await client.send_json(
        "PATCH",
        f"/api/mail/compose/{draft_id}",
        {
            "to_addrs": [{"email": "komu@firma1.example"}],
            "bcc_addrs": [{"email": "skryta@firma2.example"}],
            "subject": "Test",
        },
    )
    assert saved.status_code == 200, saved.text
    draft = await db.get(ComposeDraft, uuid.UUID(draft_id), populate_existing=True)
    assert draft is not None and draft.bcc_addrs == [{"email": "skryta@firma2.example", "name": None}]
    identity = await db.get(Identity, draft.identity_id)
    assert identity is not None
    mime = await build_mime(db, settings, draft, identity)
    assert mime["Bcc"] == "skryta@firma2.example"
    assert "skryta@firma2.example" in collect_recipients(mime)  # the sandbox guard sees it like To / Cc
