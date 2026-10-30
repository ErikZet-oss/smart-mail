"""#139 part B — Prehlásenie o zhode: golden print, PZ-RRRR-NNNN numbering, issue rules, PDF attached to a draft."""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import subprocess
import uuid
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageChops
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.ai.models import OrgSettings
from app.auth.models import Branch, Person, PersonBranch, Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.documents import conformity as cf
from app.documents.models import ConformityDeclaration
from app.mail import storage
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import TEST_DATABASE_URL, Client, FakeMailServer, make_branch, make_personal
from tests.test_branches_people_55 import PASSWORD

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "documents"
MAX_DIFF = 0.005


# --- golden print ------------------------------------------------------------------------------------------------


@pytest.mark.golden
def test_139_conformity_matches_golden(tmp_path: Path) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_fixture", ROOT / "tools" / "make_conformity_fixture.py")
    assert spec and spec.loader
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    sample = json.loads((FIXTURES / "conformity_sample.json").read_text(encoding="utf-8"))
    pdf = tmp_path / "conformity.pdf"
    pdf.write_bytes(
        tool.render_sample(
            sample,
            (FIXTURES / "conformity_stamp.png").read_bytes(),
            (FIXTURES / "conformity_signature.png").read_bytes(),
        )
    )
    exe = shutil.which("pdftoppm")
    assert exe, "pdftoppm (poppler-utils) is required for golden print tests"
    subprocess.run([exe, "-r", "150", "-png", "-singlefile", "-f", "1", "-l", "1", str(pdf), str(tmp_path / "got")])
    got = Image.open(tmp_path / "got.png").convert("RGB")
    want = Image.open(FIXTURES / "conformity_sample.png").convert("RGB")
    assert got.size == want.size
    diff = ImageChops.difference(got, want).convert("L").point(lambda v: 255 if v > 48 else 0)
    changed = diff.histogram()[255] / (got.size[0] * got.size[1])
    assert changed < MAX_DIFF, f"{changed:.3%} pixels differ (limit {MAX_DIFF:.1%}), see {tmp_path}"


def test_139_columns_follow_the_data() -> None:
    assert cf.columns([{"nazov": "A", "kod": "", "norma": "", "poznamka": ""}]) == [("nazov", "Názov výrobku")]
    items = cf.clean_items([{"nazov": " M8 ", "norma": "DIN 934"}, {"nazov": "", "kod": "X"}, {"nazov": "x" * 999}])
    assert [i["nazov"] for i in items] == ["M8", "x" * 200]  # trimmed, empty name dropped, length-limited
    assert [k for k, _ in cf.columns(items)] == ["nazov", "norma"]


def test_139_html_escapes_customer_text() -> None:
    html = cf.render_html(
        cf.DeclarationData("PZ-2026-0001", date(2026, 1, 2), "<script>x</script>", "FA", "Nitra", [{"nazov": "a"}]),
        branch=cf.Party("Nitra"),
        signer=cf.Signer("Ján", None),
        stamp_png=b"png",
        signature_png=b"png",
        ico="",
    )
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert 'font-family: "Liberation Sans"' in html  # our stylesheet is not escaped


# --- numbering ---------------------------------------------------------------------------------------------------


async def test_139_numbers_run_per_year_without_gaps(db: AsyncSession) -> None:
    assert await cf.next_number(db, date(2026, 3, 1)) == "PZ-2026-0001"
    assert await cf.next_number(db, date(2026, 12, 31)) == "PZ-2026-0002"
    assert await cf.next_number(db, date(2027, 1, 1)) == "PZ-2027-0001"  # a new year starts again
    await db.commit()
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == cf.COUNTER_SECTION))
    assert row is not None and row.data == {"year": 2027, "last": 1}


async def test_139_concurrent_issues_never_share_a_number(db: AsyncSession) -> None:
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def take() -> str:
        async with maker() as session:
            number = await cf.next_number(session, date(2026, 5, 5))
            await asyncio.sleep(0.05)  # hold the row lock a little, like a PDF render
            await session.commit()
            return number

    try:
        numbers = await asyncio.gather(*(take() for _ in range(6)))
    finally:
        await engine.dispose()
    assert sorted(numbers) == [f"PZ-2026-{i:04d}" for i in range(1, 7)]


# --- issuing ------------------------------------------------------------------------------------------------------


def _png() -> bytes:
    image = Image.new("RGBA", (40, 20), (0, 0, 0, 0))
    image.putpixel((5, 5), (0, 0, 200, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def _setup(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    *,
    role: Role = Role.sales,
    stamp: bool = True,
    signature: bool = True,
) -> tuple[Branch, Person]:
    branch, _ = await make_branch(db, "Nitra", people=0, address="Novozámocká 232, 949 01 Nitra", phone="037 000")
    if stamp:
        branch.stamp_key, _ = storage.put_bytes(settings, _png(), prefix="branch-stamps")
    manager = Person(
        branch_id=branch.id,
        first_name="Ján",
        last_name="Vedúci",
        role=Role.sales,
        is_manager=True,
        function="Vedúci pobočky",
    )
    if signature:
        manager.signature_key, _ = storage.put_bytes(settings, _png(), prefix="person-signatures")
    db.add(manager)
    acc = await make_personal(db, email="predajca@smartsro.sk", role=role)
    issuer = await db.get(Person, acc.person_id)
    assert issuer is not None
    issuer.branch_id = branch.id
    await db.commit()
    mail_server.passwords[acc.email] = PASSWORD
    assert (await client.login(acc.email, PASSWORD)).status_code == 200
    return branch, manager


BODY: dict[str, Any] = {
    "customer": "Fiktívna Stavebná s.r.o., Testovacia 1, 000 00 Vzorovo",
    "document_ref": "FA 2026/0000",
    "items": [{"nazov": "Matica M8 Zn", "kod": "TEST-1", "norma": "DIN 934"}],
}


async def test_139_issue_numbers_renders_stores_and_audits(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    _branch, manager = await _setup(client, db, mail_server, settings)
    r = await client.send_json("POST", "/api/documents/conformity", BODY)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["number"].startswith("PZ-") and out["number"].endswith("-0001") and out["signer"] == "Ján Vedúci"
    row = await db.scalar(select(ConformityDeclaration))
    assert row is not None and row.signer_person_id == manager.id and row.place == "Nitra"
    pdf = storage.get_bytes(settings, row.pdf_storage_key)
    assert pdf is not None and pdf.startswith(b"%PDF") and cf.sha256(pdf) == row.sha256 == out["sha256"]
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "document.conformity_issued"))
    assert entry is not None and entry.details is not None
    assert entry.details["number"] == out["number"] and entry.details["items"] == 1
    assert "Fiktívna" not in json.dumps(entry.details)  # no customer content in the audit

    dl = await client.get(f"/api/documents/conformity/{row.id}/pdf")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
    assert (await client.send_json("POST", "/api/documents/conformity", BODY)).json()["number"].endswith("-0002")


async def test_139_preview_stores_nothing(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    await _setup(client, db, mail_server, settings)
    r = await client.send_json("POST", "/api/documents/conformity/preview", BODY)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert await db.scalar(select(ConformityDeclaration)) is None
    assert await db.scalar(select(OrgSettings).where(OrgSettings.section == cf.COUNTER_SECTION)) is None


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"stamp": False}, 409, "no_branch_stamp"),
        ({"signature": False}, 409, "no_manager_signature"),
        ({"role": Role.warehouse}, 403, "role_not_allowed"),
        ({"role": Role.viewer}, 403, "read_only"),
    ],
)
async def test_139_blocked_issues(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    settings: Settings,
    kwargs: dict[str, Any],
    status: int,
    code: str,
) -> None:
    await _setup(client, db, mail_server, settings, **kwargs)
    r = await client.send_json("POST", "/api/documents/conformity", BODY)
    assert r.status_code == status and r.json()["detail"]["code"] == code
    assert await db.scalar(select(ConformityDeclaration)) is None


async def test_139_person_of_another_branch_is_403_unless_covering(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    await _setup(client, db, mail_server, settings)
    other, _ = await make_branch(db, "Senica", people=0)
    body = {**BODY, "branch_id": str(other.id)}
    assert (await client.send_json("POST", "/api/documents/conformity", body)).json()["detail"][
        "code"
    ] == "other_branch"
    issuer = await db.scalar(select(Person).where(Person.last_name == "Testová"))
    assert issuer is not None
    db.add(PersonBranch(person_id=issuer.id, branch_id=other.id))  # „Pôsobí aj na pobočkách“
    await db.commit()
    # covering the branch is allowed — now the other branch's own stamp is what is missing
    r = await client.send_json("POST", "/api/documents/conformity", body)
    assert r.json()["detail"]["code"] == "no_branch_stamp"


async def test_139_issue_from_a_mail_attaches_the_pdf_to_a_reply_draft(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_imap(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("app.api.documents.sync_draft_to_imap", no_imap)
    await _setup(client, db, mail_server, settings)
    mailbox = await db.scalar(select(Mailbox).where(Mailbox.email == "predajca@smartsro.sk"))
    assert mailbox is not None
    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox", selectable=True, subscribed=True)
    db.add(folder)
    await db.flush()
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=7,
        subject="Prosím atest 2.1",
        from_email="nakup@fiktivna.example",
        from_name="Nákup",
    )
    db.add(message)
    await db.commit()
    r = await client.send_json("POST", "/api/documents/conformity", {**BODY, "message_id": str(message.id)})
    assert r.status_code == 201, r.text
    draft = await db.get(ComposeDraft, uuid.UUID(r.json()["draft_id"]))
    assert draft is not None and draft.mode == "reply" and draft.subject == "Re: Prosím atest 2.1"
    att = await db.scalar(select(ComposeAttachment).where(ComposeAttachment.draft_id == draft.id))
    assert att is not None and att.filename == f"Prehlasenie_o_zhode_{r.json()['number']}.pdf"
    row = await db.scalar(select(ConformityDeclaration))
    assert row is not None and att.storage_key != row.pdf_storage_key  # removing the chip never deletes the document
