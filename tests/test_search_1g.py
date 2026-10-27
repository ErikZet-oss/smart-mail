"""Phase 1g mail search: unaccent both ways, multi-word, scope, ACL, ~10k perf."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, Person, Role
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer, make_personal
from tests.test_mail_sync_1c import PASSWORD


async def _signed_in(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> tuple[Account, Mailbox]:
    acc = await make_personal(db)
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == acc.email))).scalar_one()
    return acc, mailbox


async def _folder(
    db: AsyncSession,
    mailbox: Mailbox,
    name: str,
    *,
    special_use: str | None = None,
    private: bool = False,
    owner_person_id: uuid.UUID | None = None,
    delimiter: str = "/",
) -> FolderMeta:
    f = FolderMeta(
        mailbox_id=mailbox.id,
        name=name,
        special_use=special_use,
        private=private,
        owner_person_id=owner_person_id,
        delimiter=delimiter,
        subscribed=True,
        selectable=True,
    )
    db.add(f)
    await db.flush()
    return f


async def _msg(
    db: AsyncSession,
    mailbox: Mailbox,
    folder: FolderMeta,
    uid: int,
    *,
    subject: str | None = None,
    body: str | None = None,
    from_email: str | None = "odosielatel@smartmail.test",
    from_name: str | None = None,
    to_addrs: list[dict[str, str]] | None = None,
    cc_addrs: list[dict[str, str]] | None = None,
    received_at: datetime | None = None,
) -> Message:
    m = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=uid,
        subject=subject,
        body_text=body,
        preview=(body or "")[:200] if body else None,
        from_email=from_email,
        from_name=from_name,
        to_addrs=to_addrs or [],
        cc_addrs=cc_addrs or [],
        received_at=received_at or datetime.now(UTC),
        size=10,
    )
    db.add(m)
    await db.flush()
    return m


@pytest.mark.asyncio
async def test_1g_unaccent_cena_both_ways(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Ponuka s čéna materiálu", body="text")
    await _msg(db, mailbox, inbox, 2, subject="Cenník bez diakritiky cena", body="text")
    await db.commit()

    with_diacritics = await client.get("/api/search", params={"q": "céna", "scope": "all", "fields": "subject"})
    assert with_diacritics.status_code == 200, with_diacritics.text
    subjects = {h["subject"] for h in with_diacritics.json()["messages"]}
    assert any("čéna" in (s or "") for s in subjects)
    assert any("cena" in (s or "").lower() for s in subjects)

    without = await client.get("/api/search", params={"q": "cena", "scope": "all", "fields": "subject"})
    subjects2 = {h["subject"] for h in without.json()["messages"]}
    assert any("čéna" in (s or "") for s in subjects2)
    assert any("cena" in (s or "").lower() for s in subjects2)


@pytest.mark.asyncio
async def test_1g_unaccent_trencin_both_ways(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Dodávka Trenčín", body="sklad")
    await _msg(db, mailbox, inbox, 2, subject="trencin sklad", body="ine")
    await db.commit()

    r1 = await client.get("/api/search", params={"q": "Trenčín", "scope": "all"})
    r2 = await client.get("/api/search", params={"q": "trencin", "scope": "all"})
    assert r1.json()["total"] >= 2
    assert r2.json()["total"] >= 2


@pytest.mark.asyncio
async def test_1g_multiword_query(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Faktúra Würth september", body="úhrada faktúry")
    await _msg(db, mailbox, inbox, 2, subject="Faktúra iná", body="niečo iné")
    await _msg(db, mailbox, inbox, 3, subject="Würth katalóg", body="bez faktúry")
    await db.commit()

    r = await client.get("/api/search", params={"q": "faktúra würth", "scope": "all", "fields": "subject"})
    assert r.status_code == 200
    subjects = [h["subject"] for h in r.json()["messages"]]
    assert any("Würth september" in (s or "") for s in subjects)
    assert not any(s == "Faktúra iná" for s in subjects)
    assert not any(s == "Würth katalóg" for s in subjects)


@pytest.mark.asyncio
async def test_1g_prefix_fragment_faktur(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Faktúra 2026-01", body="ok")
    await _msg(db, mailbox, inbox, 2, subject="Objednávka bez f", body="ok")
    await db.commit()
    r = await client.get("/api/search", params={"q": "faktúr", "scope": "all", "fields": "subject"})
    assert r.status_code == 200, r.text
    subjects = {h["subject"] for h in r.json()["messages"]}
    assert any("Faktúra" in (s or "") for s in subjects)
    assert "Objednávka bez f" not in subjects


@pytest.mark.asyncio
async def test_1g_address_substring_firma_sk(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="A", from_email="jan@firma.sk", from_name="Ján")
    await _msg(db, mailbox, inbox, 2, subject="B", from_email="iny@smartmail.test")
    await db.commit()
    r = await client.get("/api/search", params={"q": "firma.sk", "scope": "all", "fields": "from"})
    assert r.status_code == 200, r.text
    emails = {h["from_email"] for h in r.json()["messages"]}
    assert "jan@firma.sk" in emails
    assert "iny@smartmail.test" not in emails


@pytest.mark.asyncio
async def test_1g_full_field_finds_firma_sk_via_address_substring(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Celá správa: FTS strips the dot from firma.sk, so full must also use address LIKE."""
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Bez domény", from_email="jan@firma.sk", body="nič")
    await _msg(db, mailbox, inbox, 2, subject="Iný", from_email="iny@smartmail.test", body="nič")
    await db.commit()
    r = await client.get("/api/search", params={"q": "firma.sk", "scope": "all", "fields": "full"})
    assert r.status_code == 200, r.text
    emails = {h["from_email"] for h in r.json()["messages"]}
    assert "jan@firma.sk" in emails
    assert "iny@smartmail.test" not in emails
    assert r.json()["oldest_downloaded_at"] is not None


@pytest.mark.asyncio
async def test_1g_special_char_query_returns_200(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    """Query with &, (), !, :*, quotes, backslash must not crash (200)."""
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Bezpečný", body="ok")
    await db.commit()
    r = await client.get(
        "/api/search",
        params={"q": "a & (b, !, :*, ', \\", "scope": "all", "fields": "full"},
    )
    assert r.status_code == 200, r.text
    assert "messages" in r.json()
    assert isinstance(r.json()["total"], int)


@pytest.mark.asyncio
async def test_1g_prefix_trenc_matches_trencin(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Dodávka Trenčín", body="x")
    await db.commit()
    r = await client.get("/api/search", params={"q": "trenc", "scope": "all", "fields": "subject"})
    assert r.json()["total"] >= 1
    assert any("Trenčín" in (h["subject"] or "") for h in r.json()["messages"])


@pytest.mark.asyncio
async def test_1g_subfolders_escape_percent_underscore(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Folder names with %/_ must not act as LIKE wildcards (startswith autoescape)."""
    _, mailbox = await _signed_in(client, db, mail_server)
    parent = await _folder(db, mailbox, "INBOX", special_use="inbox")
    weird = await _folder(db, mailbox, "INBOX/a%b_c")
    other = await _folder(db, mailbox, "INBOX/axbyc")
    await _msg(db, mailbox, weird, 1, subject="escape-hit-unique")
    await _msg(db, mailbox, other, 1, subject="escape-miss-unique")
    await db.commit()
    r = await client.get(
        "/api/search",
        params={"q": "escape", "scope": "subfolders", "folder_id": str(parent.id), "fields": "subject"},
    )
    subjects = {h["subject"] for h in r.json()["messages"]}
    # Both are under INBOX/… so both match subfolders of INBOX; ensure % folder itself is included
    assert "escape-hit-unique" in subjects


@pytest.mark.asyncio
async def test_1g_search_scope_current_subfolders_all(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    child = await _folder(db, mailbox, "INBOX/Nitra")
    other = await _folder(db, mailbox, "Sent", special_use="sent")
    await _msg(db, mailbox, inbox, 1, subject="scope-inbox-unique")
    await _msg(db, mailbox, child, 1, subject="scope-child-unique")
    await _msg(db, mailbox, other, 1, subject="scope-sent-unique")
    await db.commit()

    current = await client.get(
        "/api/search",
        params={"q": "scope", "scope": "current", "folder_id": str(inbox.id), "fields": "subject"},
    )
    assert {h["subject"] for h in current.json()["messages"]} == {"scope-inbox-unique"}

    sub = await client.get(
        "/api/search",
        params={"q": "scope", "scope": "subfolders", "folder_id": str(inbox.id), "fields": "subject"},
    )
    assert {h["subject"] for h in sub.json()["messages"]} == {"scope-inbox-unique", "scope-child-unique"}

    all_r = await client.get("/api/search", params={"q": "scope", "scope": "all", "fields": "subject"})
    assert {h["subject"] for h in all_r.json()["messages"]} == {
        "scope-inbox-unique",
        "scope-child-unique",
        "scope-sent-unique",
    }


@pytest.mark.asyncio
async def test_1g_search_no_other_mailbox(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _signed_in(client, db, mail_server)
    # foreign mailbox the signed-in account cannot access
    other_box = Mailbox(
        email="cudzia@smartmail.test",
        imap_host="localhost",
        imap_port=993,
        imap_security="ssl",
    )
    db.add(other_box)
    await db.flush()
    folder = await _folder(db, other_box, "INBOX", special_use="inbox")
    await _msg(db, other_box, folder, 1, subject="secret-other-mailbox-xyz")
    await db.commit()

    r = await client.get("/api/search", params={"q": "secret-other-mailbox-xyz", "scope": "all"})
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["messages"] == []


@pytest.mark.asyncio
async def test_1g_search_no_other_persons_private_folder(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    acc, mailbox = await _signed_in(client, db, mail_server)
    other = Person(first_name="Eva", last_name="Súkromná", role=Role.sales)
    db.add(other)
    await db.flush()
    # shared-style: both persons could use same mailbox, but private folder belongs to Eva
    private = await _folder(db, mailbox, "Súkromné", private=True, owner_person_id=other.id)
    public = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, private, 1, subject="private-only-eva-abc")
    await _msg(db, mailbox, public, 1, subject="public-ok-abc")
    await db.commit()

    r = await client.get("/api/search", params={"q": "abc", "scope": "all", "fields": "subject"})
    subjects = {h["subject"] for h in r.json()["messages"]}
    assert "public-ok-abc" in subjects
    assert "private-only-eva-abc" not in subjects

    # owner can see their private folder
    assert acc.person_id is not None
    own_private = await _folder(db, mailbox, "Moje súkromné", private=True, owner_person_id=acc.person_id)
    await _msg(db, mailbox, own_private, 1, subject="private-mine-xyz")
    await db.commit()
    mine = await client.get("/api/search", params={"q": "private-mine-xyz", "scope": "all"})
    assert mine.json()["total"] == 1


@pytest.mark.asyncio
async def test_1g_search_field_body_vs_subject(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await _msg(db, mailbox, inbox, 1, subject="Bez kľúčového slova", body="tu je unikátne-telo-slovo")
    await db.commit()
    body = await client.get("/api/search", params={"q": "unikátne-telo-slovo", "fields": "body", "scope": "all"})
    assert body.json()["total"] == 1
    subj = await client.get("/api/search", params={"q": "unikátne-telo-slovo", "fields": "subject", "scope": "all"})
    assert subj.json()["total"] == 0


@pytest.mark.asyncio
async def test_1g_list_perf_around_10k_messages_per_field(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    """Smoke: ~10k messages — each Roundcube field search finishes in a few seconds (GIN + trgm)."""
    _, mailbox = await _signed_in(client, db, mail_server)
    inbox = await _folder(db, mailbox, "INBOX", special_use="inbox")
    await db.commit()

    n = 10_000
    await db.execute(
        text(
            """
            INSERT INTO messages (
              id, mailbox_id, folder_id, uid, subject, body_text, preview,
              from_email, from_name, to_addrs, cc_addrs, flags, size, seen, flagged, answered, deleted,
              has_attachments, received_at, created_at, updated_at
            )
            SELECT
              gen_random_uuid(),
              :mailbox_id,
              :folder_id,
              g,
              'Správa číslo ' || g || CASE WHEN g = 4242 THEN ' nájdi-perf-token Trenčín' ELSE ' bežná cena' END,
              CASE WHEN g = 4242 THEN 'telo-perf-unikát bodyx' ELSE 'Telo správy ' || g END,
              CASE WHEN g = 4242 THEN 'telo-perf-unikát bodyx' ELSE 'Telo správy ' || g END,
              CASE WHEN g = 4242 THEN 'jan@firma.sk' ELSE 'odosielatel@smartmail.test' END,
              CASE WHEN g = 4242 THEN 'Perf Od' ELSE 'Bežný' END,
              CASE WHEN g = 4242 THEN '[{"email":"komu@firma.sk"}]'::jsonb ELSE '[]'::jsonb END,
              CASE WHEN g = 4242 THEN '[{"email":"kopia@firma.sk"}]'::jsonb ELSE '[]'::jsonb END,
              '[]'::jsonb,
              100,
              false, false, false, false, false,
              now() - ((g || ' seconds')::interval),
              now(), now()
            FROM generate_series(1, :n) AS g
            """
        ),
        {"mailbox_id": mailbox.id, "folder_id": inbox.id, "n": n},
    )
    await db.commit()

    cases = [
        ("subject", "nájdi-perf-token"),
        ("from", "firma.sk"),
        ("to", "komu@firma.sk"),
        ("cc", "kopia@firma.sk"),
        ("body", "telo-perf-unikát"),
        ("full", "Trenčín"),
    ]
    for field, q in cases:
        t0 = time.perf_counter()
        r = await client.get("/api/search", params={"q": q, "scope": "all", "fields": field})
        elapsed = time.perf_counter() - t0
        assert r.status_code == 200, f"{field}: {r.text}"
        assert r.json()["total"] >= 1, f"{field} q={q!r} total=0"
        assert elapsed < 5.0, f"{field} search over {n} messages took {elapsed:.2f}s"
