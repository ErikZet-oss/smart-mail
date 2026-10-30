"""Prehlásenie o zhode / atest 2.1 (#139 part B, ADR-015): preview, issue, PDF.

„Vystaviť“ is always a person's click (sales or admin of the branch, or covering it): it takes the next company-wide
number, renders the PDF with the branch stamp and the branch manager's signature, stores it with its sha256 and —
when issued from a message — attaches it to a reply draft in Koncepty. Sending stays with the person (AI level 2).
An issued declaration is never edited; a correction is a new number.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.ai.models import AiSuggestion
from app.api.mail import fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Branch, Person, PersonBranch, Role
from app.core.audit import audit
from app.core.content_disposition import content_disposition_attachment
from app.documents import conformity as cf
from app.documents.models import ConformityDeclaration
from app.mail import storage
from app.mail.compose import create_draft, sync_draft_to_imap
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import Message

router = APIRouter(prefix="/api/documents", tags=["documents"])

ISSUER_ROLES = frozenset({Role.sales, Role.admin})


class ItemIn(BaseModel):
    nazov: str = Field(default="", max_length=cf.ITEM_LIMITS["nazov"])
    kod: str = Field(default="", max_length=cf.ITEM_LIMITS["kod"])
    norma: str = Field(default="", max_length=cf.ITEM_LIMITS["norma"])
    poznamka: str = Field(default="", max_length=cf.ITEM_LIMITS["poznamka"])


class DeclarationIn(BaseModel):
    branch_id: uuid.UUID | None = None  # default: the active person's branch
    customer: str = Field(min_length=1, max_length=500)
    document_ref: str = Field(default="", max_length=120)
    place: str | None = Field(default=None, max_length=80)  # default: the branch's town
    issued_on: date | None = None  # default: today
    items: list[ItemIn] = Field(min_length=1, max_length=cf.MAX_ITEMS)
    message_id: uuid.UUID | None = None  # issue from a mail → attach to a reply draft
    suggestion_id: uuid.UUID | None = None  # #139 C: issued from the AI card → the suggestion becomes „approved“

    @field_validator("customer")
    @classmethod
    def _customer(cls, value: str) -> str:
        return value.strip()


class DeclarationOut(BaseModel):
    id: str
    number: str
    issued_on: str
    branch_id: str
    signer: str
    items: int
    sha256: str
    draft_id: str | None = None


def _town(branch: Branch) -> str:
    """„Novozámocká 232, 949 01 Nitra“ → „Nitra“ (the default place)."""
    tail = (branch.address or "").rsplit(",", 1)[-1].strip()
    parts = tail.split()
    return " ".join(p for p in parts if not p.isdigit()) or branch.name


async def _covers(db: DB, person: Person, branch: Branch) -> bool:
    if person.branch_id == branch.id:
        return True
    row = await db.get(PersonBranch, {"person_id": person.id, "branch_id": branch.id})
    return row is not None


async def _context(db: DB, person: Person, body: DeclarationIn) -> tuple[Branch, Person, list[dict[str, str]]]:
    if person.role not in ISSUER_ROLES:
        raise fail(403, "role_not_allowed")
    branch_id = body.branch_id or person.branch_id
    branch = await db.get(Branch, branch_id) if branch_id else None
    if branch is None:
        raise fail(422, "branch_required")
    if person.role != Role.admin and not await _covers(db, person, branch):
        raise fail(403, "other_branch")
    if not branch.stamp_key:
        raise fail(409, "no_branch_stamp")
    signer = await db.scalar(
        select(Person)
        .where(Person.branch_id == branch.id, Person.is_manager.is_(True), Person.active.is_(True))
        .where(Person.signature_key.is_not(None))
        .order_by(Person.last_name, Person.first_name)
        .limit(1)
    )
    if signer is None:
        raise fail(409, "no_manager_signature")
    items = cf.clean_items([i.model_dump() for i in body.items])
    if not items:
        raise fail(422, "items_required")
    return branch, signer, items


async def _render(db: DB, settings: SettingsDep, branch: Branch, signer: Person, data: cf.DeclarationData) -> bytes:
    stamp = storage.get_bytes(settings, branch.stamp_key or "")
    signature = storage.get_bytes(settings, signer.signature_key or "")
    if not stamp:
        raise fail(409, "no_branch_stamp")
    if not signature:
        raise fail(409, "no_manager_signature")
    html = cf.render_html(
        data,
        branch=cf.Party(branch.name, branch.address, branch.phone),
        signer=cf.Signer(signer.full_name, signer.function),
        stamp_png=stamp,
        signature_png=signature,
        ico=await cf.company_ico(db),
    )
    return await asyncio.to_thread(cf.render_pdf, html)


def _data(body: DeclarationIn, branch: Branch, number: str, items: list[dict[str, str]]) -> cf.DeclarationData:
    return cf.DeclarationData(
        number=number,
        issued_on=body.issued_on or datetime.now(UTC).date(),
        customer=body.customer,
        document_ref=body.document_ref.strip(),
        place=(body.place or "").strip() or _town(branch),
        items=items,
    )


def _pdf(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/conformity/preview")
async def preview_declaration(
    body: DeclarationIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> Response:
    """The PDF as it will look, without a number — nothing is stored or audited."""
    branch, signer, items = await _context(db, person, body)
    pdf = await _render(db, settings, branch, signer, _data(body, branch, "NÁHĽAD", items))
    return _pdf(pdf, "prehlasenie-o-zhode-nahlad.pdf")


@router.post("/conformity", status_code=201)
async def issue_declaration(
    body: DeclarationIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> DeclarationOut:
    branch, signer, items = await _context(db, person, body)
    source: Message | None = None
    mailbox = None
    if body.message_id is not None:
        source = await db.get(Message, body.message_id)
        mailboxes = {m.id: m for m in await accessible_mailboxes(db, ctx.account.id)}
        if source is None or source.mailbox_id not in mailboxes:
            raise fail(404, "message_not_found")
        mailbox = mailboxes[source.mailbox_id]

    today = body.issued_on or datetime.now(UTC).date()
    number = await cf.next_number(db, today)  # locked until this transaction commits — no duplicates
    data = _data(body, branch, number, items)
    pdf = await _render(db, settings, branch, signer, data)
    digest = cf.sha256(pdf)
    key, _ = storage.put_bytes(settings, pdf, prefix="documents/conformity")
    row = ConformityDeclaration(
        number=number,
        branch_id=branch.id,
        prepared_by_person_id=person.id,
        signer_person_id=signer.id,
        account_id=ctx.account.id,
        customer_text=data.customer,
        document_ref=data.document_ref,
        items=items,
        place=data.place,
        issued_on=data.issued_on,
        pdf_storage_key=key,
        sha256=digest,
        message_id=source.id if source else None,
        thread_id=source.thread_id if source else None,
    )
    db.add(row)
    await db.flush()

    draft_id: str | None = None
    if source is not None and mailbox is not None:
        draft = await create_draft(
            db,
            settings,
            mailbox=mailbox,
            account_id=ctx.account.id,
            person=await db.get(Person, person.id),
            branch=await db.get(Branch, person.branch_id) if person.branch_id else None,
            mode="reply",
            source=source,
        )
        # an own copy: removing the chip from the draft must never delete the issued document
        att_key, _ = storage.put_bytes(settings, pdf, prefix=f"compose/{draft.id}")
        db.add(
            ComposeAttachment(
                draft_id=draft.id,
                filename=f"Prehlasenie_o_zhode_{number}.pdf",
                content_type="application/pdf",
                size=len(pdf),
                storage_key=att_key,
                sha256=digest,
                av_status="clean",  # rendered by the server from our own template
                is_inline=False,
            )
        )
        draft_id = str(draft.id)

    if body.suggestion_id is not None:
        suggestion = await db.get(AiSuggestion, body.suggestion_id)
        if (
            suggestion is not None
            and suggestion.suggestion_type == "conformity_declaration"
            and suggestion.status == "pending"
            and source is not None
            and suggestion.message_id == source.id
        ):
            suggestion.status = "approved"
            suggestion.decided_by = person.id
            suggestion.decided_at = datetime.now(UTC)
            suggestion.final_payload = {
                "number": number,
                "customer": data.customer,
                "document_ref": data.document_ref,
                "items": items,
            }
            suggestion.diff = {"edited": (suggestion.payload or {}).get("items") != items}
    audit(
        db,
        "document.conformity_issued",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="conformity_declaration",
        object_id=str(row.id),
        details={
            "number": number,
            "branch_id": str(branch.id),
            "prepared_by": str(person.id),
            "signer": str(signer.id),
            "document_ref": data.document_ref,
            "items": len(items),
            "sha256": digest,
            "draft_id": draft_id,
        },
    )
    await db.commit()
    if draft_id is not None:
        draft_row = await db.get(ComposeDraft, uuid.UUID(draft_id))
        if draft_row is not None:
            await sync_draft_to_imap(db, settings, draft_row)  # waits in Koncepty; sending is the person's click
            await db.commit()
    return DeclarationOut(
        id=str(row.id),
        number=number,
        issued_on=data.issued_on.isoformat(),
        branch_id=str(branch.id),
        signer=signer.full_name,
        items=len(items),
        sha256=digest,
        draft_id=draft_id,
    )


class BranchChoice(BaseModel):
    id: str
    name: str
    ready: bool  # stamp + an active manager with a signature


@router.get("/conformity/branches")
async def conformity_branches(ctx: Auth, person: ActivePerson, db: DB) -> list[BranchChoice]:
    """Branches this person may issue for (pilot 2026-10-30: a personal account without a branch could not issue at
    all). Admin: every branch; sales: own branch + branches covered in „Pôsobí aj na pobočkách“; others: none.
    The person's own branch comes first."""
    if person.role not in ISSUER_ROLES:
        return []
    if person.role == Role.admin:
        branches = list((await db.scalars(select(Branch).order_by(Branch.name))).all())
    else:
        covered = select(PersonBranch.branch_id).where(PersonBranch.person_id == person.id)
        query = select(Branch).where((Branch.id == person.branch_id) | Branch.id.in_(covered)).order_by(Branch.name)
        branches = list((await db.scalars(query)).all())
    branches.sort(key=lambda b: b.id != person.branch_id)
    signers = set(
        (
            await db.scalars(
                select(Person.branch_id).where(
                    Person.is_manager.is_(True), Person.active.is_(True), Person.signature_key.is_not(None)
                )
            )
        ).all()
    )
    return [BranchChoice(id=str(b.id), name=b.name, ready=bool(b.stamp_key) and b.id in signers) for b in branches]


@router.get("/conformity/{declaration_id}/pdf")
async def declaration_pdf(
    declaration_id: uuid.UUID, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> Response:
    row = await db.get(ConformityDeclaration, declaration_id)
    if row is None:
        raise fail(404, "not_found")
    branch = await db.get(Branch, row.branch_id)
    if branch is None or (person.role != Role.admin and not await _covers(db, person, branch)):
        raise fail(404, "not_found")
    data = storage.get_bytes(settings, row.pdf_storage_key)
    if data is None:
        raise fail(410, "pdf_missing")
    return _pdf(data, f"Prehlasenie_o_zhode_{row.number}.pdf")
