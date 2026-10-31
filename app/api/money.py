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
from sqlalchemy import or_, select

from app.api.mail import fail
from app.auth.deps import DB, ActivePerson, Auth, SettingsDep
from app.auth.models import Role
from app.core.audit import audit
from app.core.config import Settings
from app.mail.export import visible_to
from app.mail.mailboxes import accessible_mailboxes
from app.mail.models import FolderMeta, Message
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.matching import counterparty, match_sender
from app.money.models import EmailCompanyLink, MoneyCompany, MoneyPerson
from app.money.schemas import Activity, Delivery, IssuedInvoice, Order

router = APIRouter(prefix="/api/money", tags=["money"])
LINK_ROLES = frozenset({Role.admin, Role.sales, Role.accounting, Role.warehouse})
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


def receivables_summary(rows: list[IssuedInvoice], today: date) -> Receivables:
    overdue = [r for r in rows if r.due_on is not None and r.due_on < today]
    oldest = min((r.due_on for r in overdue if r.due_on), default=None)
    return Receivables(
        open_count=len(rows),
        open_total=sum((r.remaining for r in rows), Decimal("0")),
        overdue_count=len(overdue),
        overdue_total=sum((r.remaining for r in overdue), Decimal("0")),
        oldest_overdue_days=(today - oldest).days if oldest else None,
        mixed_currency=len({r.currency_id for r in rows}) > 1,
        items=sorted(rows, key=lambda r: r.due_on or date.max)[:LIST_ROWS],
    )


@router.get("/companies/{money_id}/card")
async def company_card(money_id: uuid.UUID, ctx: Auth, db: DB, settings: SettingsDep) -> CardOut:
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
            receivables = receivables_summary(await bridge.receivables(money_id), today)
        except BridgeUnavailable as exc:
            receivables.error = exc.code
        try:
            orders.items = (await bridge.orders(money_id, since))[:LIST_ROWS]
        except BridgeUnavailable as exc:
            orders.error = exc.code
        try:
            deliveries.items = (await bridge.deliveries(money_id, since))[:LIST_ROWS]
        except BridgeUnavailable as exc:
            deliveries.error = exc.code
        try:
            activities.items = (await bridge.activities(money_id))[:LIST_ROWS]
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
