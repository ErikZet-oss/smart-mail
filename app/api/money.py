"""Phase 3c: Zákazník panel (W3b / M10) — sender → Money company, the company card, „Priradiť k firme“.

Read-only towards Money. Everything answers 404 `money_disabled` while FEATURE_MONEY is off. The card fetches its
live parts from the bridge one by one: one part failing („Money nedostupné“) never hides the others or the mail.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select

from app.ai.models import Classification
from app.api.mail import _mailbox, fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Branch, Person, Role
from app.core.audit import AuditLog, audit
from app.core.config import Settings
from app.mail.compose import sync_draft_to_imap
from app.mail.compose_models import ComposeDraft
from app.mail.export import visible_to
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import FolderMeta, Mailbox, Message
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.invoice_attach import draft_body, evaluate
from app.money.invoice_draft import InvoiceDraftError, build_invoice_draft
from app.money.matching import counterparty, match_sender
from app.money.models import EmailCompanyLink, MoneyCompany, MoneyPerson
from app.money.reminders import AUDIT_ACTION, build_reminder_draft, overdue_debtors
from app.money.schemas import Activity, Delivery, IssuedInvoice, Order

router = APIRouter(prefix="/api/money", tags=["money"])
LINK_ROLES = frozenset({Role.admin, Role.sales, Role.accounting, Role.warehouse})
SEND_ROLES = frozenset({Role.admin, Role.sales, Role.accounting})  # sending invoices (PRODUCT_SPEC §4)
LIST_ROWS = 5
HISTORY_DAYS = 365


def _enabled(settings: Settings) -> None:
    if not settings.feature_money:
        raise fail(404, "money_disabled")


class CompanyBrief(BaseModel):
    money_id: uuid.UUID
    name: str
    code: str | None
    ico: str | None
    dic: str | None
    icdph: str | None
    email: str | None
    discount_pct: Decimal | None
    due_days: int | None


def _brief(c: MoneyCompany) -> CompanyBrief:
    return CompanyBrief(
        money_id=c.money_id,
        name=c.name,
        code=c.code,
        ico=c.ico,
        dic=c.dic,
        icdph=c.icdph,
        email=c.email,
        discount_pct=c.discount_pct,
        due_days=c.due_days,
    )


class CustomerMatchOut(BaseModel):
    email: str | None
    method: Literal["confirmed", "person", "company_email", "ico", "domain"] | None
    confidence: float
    needs_confirmation: bool
    company: CompanyBrief | None
    candidates: list[CompanyBrief]


class Part[T](BaseModel):
    """One live section of the card; `error` = money_unavailable | waiting_for_probe | …"""

    error: str | None = None
    items: list[T] = Field(default_factory=list)


class Receivables(BaseModel):
    error: str | None = None
    open_count: int = 0
    open_total: Decimal = Decimal("0")
    overdue_count: int = 0
    overdue_total: Decimal = Decimal("0")
    oldest_overdue_days: int | None = None
    mixed_currency: bool = False
    items: list[IssuedInvoice] = Field(default_factory=list)


class PersonOut(BaseModel):
    money_id: uuid.UUID
    name: str | None
    function: str | None
    email: str | None
    phone: str | None


class CardOut(BaseModel):
    company: CompanyBrief
    receivables: Receivables
    orders: Part[Order]
    deliveries: Part[Delivery]
    activities: Part[Activity]
    persons: list[PersonOut]


async def _message(db: DB, account_id: uuid.UUID, person_id: uuid.UUID | None, message_id: uuid.UUID) -> Message:
    message = await db.get(Message, message_id)
    allowed = {m.id for m in await accessible_mailboxes(db, account_id)}
    if message is None or message.mailbox_id not in allowed:
        raise fail(404, "message_not_found")
    folder = await db.get(FolderMeta, message.folder_id)
    if folder is None or not visible_to(folder, person_id):
        raise fail(404, "message_not_found")  # someone else's private folder (ADR-009, same rule as search)
    return message


@router.get("/messages/{message_id}/customer")
async def message_customer(message_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> CustomerMatchOut:
    _enabled(settings)
    message = await _message(db, ctx.account.id, ctx.person.id if ctx.person else None, message_id)
    email = counterparty(message, settings)
    if email is None:
        return CustomerMatchOut(
            email=None, method=None, confidence=0.0, needs_confirmation=False, company=None, candidates=[]
        )
    found = await match_sender(db, email, message.body_text, settings)
    return CustomerMatchOut(
        email=email,
        method=found.method,
        confidence=found.confidence,
        needs_confirmation=found.needs_confirmation,
        company=_brief(found.company) if found.company else None,
        candidates=[_brief(c) for c in found.candidates],
    )


def receivables_summary(rows: list[IssuedInvoice], today: date, limit: int = LIST_ROWS) -> Receivables:
    overdue = [r for r in rows if r.due_on is not None and r.due_on < today]
    oldest = min((r.due_on for r in overdue if r.due_on), default=None)
    return Receivables(
        open_count=len(rows),
        open_total=sum((r.remaining for r in rows), Decimal("0")),
        overdue_count=len(overdue),
        overdue_total=sum((r.remaining for r in overdue), Decimal("0")),
        oldest_overdue_days=(today - oldest).days if oldest else None,
        mixed_currency=len({r.currency_id for r in rows}) > 1,
        items=sorted(rows, key=lambda r: r.due_on or date.max)[:limit],
    )


@router.get("/companies/{money_id}/card")
async def company_card(
    money_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep, rows: int = Query(default=LIST_ROWS, ge=1, le=50)
) -> CardOut:
    """Zákazník panel (5 rows) and W9a Doklady (`rows` up to 50)."""
    _enabled(settings)
    company = await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == money_id))
    if company is None:
        raise fail(404, "company_not_found")
    persons = (
        await db.scalars(
            select(MoneyPerson)
            .where(MoneyPerson.company_money_id == money_id, MoneyPerson.active.is_(True))
            .order_by(MoneyPerson.last_name, MoneyPerson.first_name)
            .limit(20)
        )
    ).all()
    today = datetime.now(UTC).date()
    since = today - timedelta(days=HISTORY_DAYS)
    receivables = Receivables()
    orders: Part[Order] = Part()
    deliveries: Part[Delivery] = Part()
    activities: Part[Activity] = Part()
    async with BridgeClient(settings) as bridge:
        try:
            receivables = receivables_summary(await bridge.receivables(money_id), today, rows)
        except BridgeUnavailable as exc:
            receivables.error = exc.code
        try:
            orders.items = (await bridge.orders(money_id, since))[:rows]
        except BridgeUnavailable as exc:
            orders.error = exc.code
        try:
            deliveries.items = (await bridge.deliveries(money_id, since))[:rows]
        except BridgeUnavailable as exc:
            deliveries.error = exc.code
        try:
            activities.items = (await bridge.activities(money_id))[:rows]
        except BridgeUnavailable as exc:
            activities.error = exc.code
    return CardOut(
        company=_brief(company),
        receivables=receivables,
        orders=orders,
        deliveries=deliveries,
        activities=activities,
        persons=[
            PersonOut(money_id=p.money_id, name=p.name, function=p.function, email=p.email, phone=p.phone)
            for p in persons
        ],
    )


@router.get("/companies/search")
async def search_companies(
    ctx: Auth, db: DB, settings: SettingsDep, q: str = Query(min_length=2, max_length=80)
) -> list[CompanyBrief]:
    """„Priradiť k firme“: name, IČO or code in the read cache (no Money call)."""
    _enabled(settings)
    text = q.strip()
    pattern = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    rows = await db.scalars(
        select(MoneyCompany)
        .where(
            MoneyCompany.active.is_(True),
            or_(
                MoneyCompany.name.ilike(pattern, escape="\\"),
                MoneyCompany.ico == text.replace(" ", ""),
                MoneyCompany.code.ilike(pattern, escape="\\"),
            ),
        )
        .order_by(MoneyCompany.name)
        .limit(20)
    )
    return [_brief(c) for c in rows]


class LinkIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    company_money_id: uuid.UUID

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or " " in value:
            raise ValueError("invalid e-mail")
        return value


@router.post("/links")
async def link_email(body: LinkIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep) -> CustomerMatchOut:
    """A person confirms „this address belongs to this company“ (also confirms a domain match once)."""
    _enabled(settings)
    if person.role not in LINK_ROLES:
        raise fail(403, "role_not_allowed")
    if settings.is_internal_address(body.email):
        raise fail(422, "internal_address")
    company = await db.scalar(
        select(MoneyCompany).where(MoneyCompany.money_id == body.company_money_id, MoneyCompany.active.is_(True))
    )
    if company is None:
        raise fail(404, "company_not_found")
    link = await db.scalar(select(EmailCompanyLink).where(EmailCompanyLink.email == body.email))
    before = str(link.company_money_id) if link else None
    if link is None:
        link = EmailCompanyLink(email=body.email, company_money_id=company.money_id)
        db.add(link)
    link.company_money_id = company.money_id
    link.confirmed_by_person_id = person.id
    link.confirmed_by_account_id = ctx.account.id
    audit(
        db,
        "money.email_linked",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="email_company_link",
        object_id=body.email,
        details={"company_money_id": str(company.money_id), "before": before},
    )
    await db.commit()
    return CustomerMatchOut(
        email=body.email,
        method="confirmed",
        confidence=1.0,
        needs_confirmation=False,
        company=_brief(company),
        candidates=[],
    )


@router.delete("/links")
async def unlink_email(
    ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep, email: str = Query(max_length=320)
) -> dict[str, bool]:
    _enabled(settings)
    if person.role not in LINK_ROLES:
        raise fail(403, "role_not_allowed")
    link = await db.scalar(select(EmailCompanyLink).where(EmailCompanyLink.email == email.strip().lower()))
    if link is None:
        raise fail(404, "link_not_found")
    audit(
        db,
        "money.email_unlinked",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="email_company_link",
        object_id=link.email,
        details={"company_money_id": str(link.company_money_id)},
    )
    await db.delete(link)
    await db.commit()
    return {"deleted": True}


class InvoiceDraftIn(BaseModel):
    number: str = Field(min_length=3, max_length=40)


class InvoiceDraftOut(BaseModel):
    draft_id: str


@router.post("/messages/{message_id}/invoice-draft")
async def invoice_draft(
    message_id: uuid.UUID, body: InvoiceDraftIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> InvoiceDraftOut:
    """Zákazník card „Poslať“ (Phase 3d): the same checks as the AI suggestion, then a reply draft with the PDF.
    Nothing is sent here — the person checks and sends the draft in W4."""
    _enabled(settings)
    if person.role not in SEND_ROLES:
        raise fail(403, "role_not_allowed")
    message = await _message(db, ctx.account.id, person.id, message_id)
    email = counterparty(message, settings)
    if email is None:
        raise fail(409, "no_recipient")
    mailbox = await db.get(Mailbox, message.mailbox_id)
    assert mailbox is not None
    cls = await db.scalar(select(Classification).where(Classification.message_id == message.id).limit(1))
    language = cls.language if cls else None
    async with BridgeClient(settings) as bridge:
        try:
            ev = await evaluate(
                db,
                settings,
                bridge,
                email=email,
                body_text=message.body_text,
                refs=[body.number.strip()],
                language=language,
            )
            if ev.blocked:
                raise fail(409, "suggestion_blocked", checks=ev.checks)
            draft = await build_invoice_draft(
                db,
                settings,
                bridge,
                mailbox=mailbox,
                message=message,
                account_id=ctx.account.id,
                person=await db.get(Person, person.id),
                branch=await db.get(Branch, person.branch_id) if person.branch_id else None,
                evaluation=ev,
                body=draft_body(language, [i.number for i in ev.invoices]),
                language=language,
            )
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
        except InvoiceDraftError as exc:
            raise fail(409, exc.code, number=exc.number) from None
    audit(
        db,
        "money.invoice_draft",
        account_id=ctx.account.id,
        person_id=person.id,
        object_type="compose_draft",
        object_id=str(draft.id),
        details={"invoices": [i.number for i in ev.invoices], "company_money_id": str(ev.company_money_id)},
    )
    await db.commit()
    await sync_draft_to_imap(db, settings, draft)
    await db.commit()
    return InvoiceDraftOut(draft_id=str(draft.id))


# ----- W8b Upomienky (Phase 3e) -----

REMINDER_ROLES = frozenset({Role.admin, Role.sales, Role.accounting})


class DebtorOut(BaseModel):
    company: CompanyBrief
    contact: str | None
    overdue_total: Decimal
    invoice_count: int
    oldest_days: int
    last_reminder_at: datetime | None
    invoices: list[IssuedInvoice]


class RemindersIn(BaseModel):
    mailbox: str = Field(default="default", max_length=320)
    company_money_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)
    tone: Literal["polite", "firm"] = "polite"


class ReminderResult(BaseModel):
    company_money_id: uuid.UUID
    draft_id: str | None
    error: str | None
    number: str | None = None


class ReminderHistoryRow(BaseModel):
    at: datetime
    company_money_id: str
    company_name: str | None
    draft_id: str | None
    draft_status: str | None
    tone: str | None
    invoices: list[str]


def _reminder_role(person: Person) -> None:
    if person.role not in REMINDER_ROLES:
        raise fail(403, "role_not_allowed")


@router.get("/reminders")
async def list_debtors(ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep) -> list[DebtorOut]:
    """Customers with overdue invoices, highest sum first (live from Money; cache for names and contacts)."""
    _enabled(settings)
    _reminder_role(person)
    today = datetime.now(UTC).date()
    async with BridgeClient(settings) as bridge:
        try:
            debtors = await overdue_debtors(db, bridge, today)
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
    return [
        DebtorOut(
            company=_brief(d.company),
            contact=d.contact,
            overdue_total=d.total,
            invoice_count=len(d.invoices),
            oldest_days=d.oldest_days(today),
            last_reminder_at=d.last_reminder_at,
            invoices=d.invoices,
        )
        for d in debtors
    ]


@router.post("/reminders/drafts")
async def prepare_reminders(
    body: RemindersIn, ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep
) -> list[ReminderResult]:
    """One draft per selected customer in Koncepty (E2 + PDFs). The person reviews and sends each — level 2."""
    _enabled(settings)
    _reminder_role(person)
    mailbox = await _mailbox(db, ctx, body.mailbox)  # same `default` / id / address rule as the mail API
    today = datetime.now(UTC).date()
    person_row = await db.get(Person, person.id)
    branch = await db.get(Branch, person.branch_id) if person.branch_id else None
    results: list[ReminderResult] = []
    drafts: list[ComposeDraft] = []
    async with BridgeClient(settings) as bridge:
        try:
            debtors = {d.company.money_id: d for d in await overdue_debtors(db, bridge, today)}
        except BridgeUnavailable as exc:
            raise fail(503, "money_unavailable", reason=exc.code) from None
        for company_id in dict.fromkeys(body.company_money_ids):
            debtor = debtors.get(company_id)
            if debtor is None:
                results.append(ReminderResult(company_money_id=company_id, draft_id=None, error="nothing_overdue"))
                continue
            try:
                draft = await build_reminder_draft(
                    db,
                    settings,
                    bridge,
                    mailbox=mailbox,
                    account_id=ctx.account.id,
                    person=person_row,
                    branch=branch,
                    debtor=debtor,
                    tone=body.tone,
                    today=today,
                )
            except InvoiceDraftError as exc:
                results.append(
                    ReminderResult(company_money_id=company_id, draft_id=None, error=exc.code, number=exc.number)
                )
                continue
            except BridgeUnavailable:
                results.append(ReminderResult(company_money_id=company_id, draft_id=None, error="money_unavailable"))
                break
            drafts.append(draft)
            audit(
                db,
                AUDIT_ACTION,
                account_id=ctx.account.id,
                person_id=person.id,
                object_type="money_company",
                object_id=str(company_id),
                details={
                    "draft_id": str(draft.id),
                    "tone": body.tone,
                    "invoices": [i.number for i in debtor.invoices[:30]],
                    "company_name": debtor.company.name,
                },
            )
            results.append(ReminderResult(company_money_id=company_id, draft_id=str(draft.id), error=None))
    await db.commit()
    for draft in drafts:
        await sync_draft_to_imap(db, settings, draft)
    await db.commit()
    return results


@router.get("/reminders/history")
async def reminder_history(ctx: Auth, person: ActivePerson, db: DB, settings: SettingsDep) -> list[ReminderHistoryRow]:
    """„Odoslané upomienky“: prepared reminders (audit) with the current state of their draft."""
    _enabled(settings)
    _reminder_role(person)
    rows = (
        await db.scalars(
            select(AuditLog).where(AuditLog.action == AUDIT_ACTION).order_by(AuditLog.created_at.desc()).limit(100)
        )
    ).all()
    ids = [uuid.UUID(str(r.details.get("draft_id"))) for r in rows if (r.details or {}).get("draft_id")]
    statuses = {
        str(d.id): d.status for d in (await db.scalars(select(ComposeDraft).where(ComposeDraft.id.in_(ids)))).all()
    }
    out = []
    for r in rows:
        details = r.details or {}
        draft_id = str(details.get("draft_id")) if details.get("draft_id") else None
        out.append(
            ReminderHistoryRow(
                at=r.created_at,
                company_money_id=str(r.object_id),
                company_name=details.get("company_name"),
                draft_id=draft_id,
                draft_status=statuses.get(draft_id or "", "deleted" if draft_id else None),
                tone=details.get("tone"),
                invoices=[str(n) for n in details.get("invoices") or []],
            )
        )
    return out


# ----- W9a Zákazník 360 + Money in global search (Phase 3g) -----


class CompanyMailOut(BaseModel):
    id: str
    mailbox_id: str
    thread_id: str | None
    subject: str | None
    from_name: str | None
    from_email: str | None
    received_at: datetime | None
    direction: Literal["in", "out"]


async def company_addresses(db: DB, money_id: uuid.UUID) -> set[str]:
    """Every address that belongs to the company: Money e-mails, Money persons, person-confirmed links."""
    company = await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == money_id))
    if company is None:
        raise fail(404, "company_not_found")
    found = set(company.emails or [])
    found |= {
        e
        for e in await db.scalars(
            select(MoneyPerson.email).where(MoneyPerson.company_money_id == money_id, MoneyPerson.email.is_not(None))
        )
        if e
    }
    found |= set(await db.scalars(select(EmailCompanyLink.email).where(EmailCompanyLink.company_money_id == money_id)))
    return {e.lower() for e in found if "@" in e}


@router.get("/companies/{money_id}/emails")
async def company_emails(
    money_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep, limit: int = Query(default=50, ge=1, le=200)
) -> list[CompanyMailOut]:
    """W9a E-maily: mail from or to the company's addresses in the mailboxes this login sees (private folders of
    other persons excluded, ADR-009)."""
    _enabled(settings)
    addresses = await company_addresses(db, money_id)
    if not addresses:
        return []
    mailboxes = [m.id for m in await accessible_mailboxes(db, ctx.account.id)]
    to_match = [Message.to_addrs.contains([{"email": a}]) for a in sorted(addresses)[:50]]
    rows = await db.execute(
        select(Message, FolderMeta)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .where(Message.mailbox_id.in_(mailboxes), Message.deleted.is_(False))
        .where(or_(func.lower(Message.from_email).in_(addresses), *to_match))
        .order_by(Message.received_at.desc().nulls_last())
        .limit(limit * 2)
    )
    person_id = ctx.person.id if ctx.person else None
    out: list[CompanyMailOut] = []
    for message, folder in rows.all():
        if not visible_to(folder, person_id):
            continue
        out.append(
            CompanyMailOut(
                id=str(message.id),
                mailbox_id=str(message.mailbox_id),
                thread_id=str(message.thread_id) if message.thread_id else None,
                subject=message.subject,
                from_name=message.from_name,
                from_email=message.from_email,
                received_at=message.received_at,
                direction="in" if (message.from_email or "").lower() in addresses else "out",
            )
        )
        if len(out) >= limit:
            break
    return out


class MoneySearchOut(BaseModel):
    companies: list[CompanyBrief]
    invoices: list[IssuedInvoice]
    invoices_error: str | None = None


@router.get("/search")
async def money_search(
    ctx: Auth, db: DB, settings: SettingsDep, q: str = Query(min_length=2, max_length=80)
) -> MoneySearchOut:
    """Global search / Ctrl+K group „Firmy“ (cache) and „Doklady“ (invoice number, live). Invoices only for the
    roles that may send them; Money down never breaks the rest of the search."""
    _enabled(settings)
    companies = await search_companies(ctx, db, settings, q)
    out = MoneySearchOut(companies=companies[:8], invoices=[])
    text = q.strip()
    role = ctx.person.role if ctx.person else None
    if role in SEND_ROLES and sum(c.isdigit() for c in text) >= 4 and not any(c in "~#|()" for c in text):
        async with BridgeClient(settings) as bridge:
            try:
                found = await bridge.search_invoices(number=text.replace(" ", ""))
                out.invoices = found.items[:8]
            except BridgeUnavailable as exc:
                out.invoices_error = exc.code
    return out
