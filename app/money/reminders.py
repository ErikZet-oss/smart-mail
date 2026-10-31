"""Phase 3e: W8b Upomienky — customers with overdue invoices and reminder drafts (E2) with Money's own PDFs.

MONEY_API §5.2: Smart Mail does not edit reminder dates in Money. A reminder is a draft in Koncepty to the company's
own e-mail (strong match only), with a table of the overdue invoices and their original PDFs; the person reviews and
sends it (level 2). The send-time recipient check of 3d applies (attachment marker).
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Person
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail import storage
from app.mail.compose import create_draft
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.models import Mailbox
from app.money.bridge_client import BridgeClient
from app.money.invoice_attach import STRONG, load_reports, pick_report, storage_prefix
from app.money.invoice_draft import InvoiceDraftError, pdf_filename
from app.money.matching import match_sender
from app.money.models import MoneyCompany
from app.money.schemas import IssuedInvoice

Tone = Literal["polite", "firm"]
AUDIT_ACTION = "money.reminder_prepared"
MAX_PAGES = 50
PAGE = 200
MAX_PER_REMINDER = 30

SUBJECT: dict[Tone, str] = {
    "polite": "Pripomienka neuhradených faktúr",
    "firm": "Upomienka – neuhradené faktúry po splatnosti",
}
INTRO: dict[Tone, str] = {
    "polite": (
        "Dobrý deň,\n\ndovoľujeme si Vás upozorniť, že podľa našej evidencie zostávajú neuhradené tieto faktúry. "
        "Ak ste ich medzičasom uhradili, považujte prosím túto správu za bezpredmetnú."
    ),
    "firm": (
        "Dobrý deň,\n\nnapriek splatnosti evidujeme neuhradené faktúry uvedené nižšie. "
        "Prosíme Vás o ich úhradu bez zbytočného odkladu."
    ),
}
OUTRO = "Kópie faktúr sú v prílohe.\n\nS pozdravom"


@dataclass
class Debtor:
    company: MoneyCompany
    invoices: list[IssuedInvoice] = field(default_factory=list)
    last_reminder_at: datetime | None = None

    @property
    def total(self) -> Decimal:
        return sum((i.remaining for i in self.invoices), Decimal("0"))

    def oldest_days(self, today: date) -> int:
        dues = [i.due_on for i in self.invoices if i.due_on]
        return (today - min(dues)).days if dues else 0

    @property
    def contact(self) -> str | None:
        """The company's own e-mail from Money (billing contact); `Email` first, then the connections."""
        if self.company.email and "@" in self.company.email:
            return self.company.email.strip().lower()
        return self.company.emails[0] if self.company.emails else None


async def overdue_debtors(db: AsyncSession, bridge: BridgeClient, today: date) -> list[Debtor]:
    """All open invoices due before today, grouped by the cached company. Raises `BridgeUnavailable`."""
    invoices: list[IssuedInvoice] = []
    start = 0
    for _ in range(MAX_PAGES):
        page = await bridge.overdue(today, start, PAGE)
        invoices += page.items
        if page.next_from is None:
            break
        start = page.next_from
    by_company: dict[uuid.UUID, list[IssuedInvoice]] = {}
    for inv in invoices:
        if inv.company_id is not None and inv.remaining > 0:
            by_company.setdefault(inv.company_id, []).append(inv)
    if not by_company:
        return []
    companies = (
        await db.scalars(select(MoneyCompany).where(MoneyCompany.money_id.in_(list(by_company)), MoneyCompany.active))
    ).all()
    last = await last_reminders(db)
    debtors = [
        Debtor(
            company=c,
            invoices=sorted(by_company[c.money_id], key=lambda i: i.due_on or date.min),
            last_reminder_at=last.get(str(c.money_id)),
        )
        for c in companies
    ]
    return sorted(debtors, key=lambda d: d.total, reverse=True)


async def last_reminders(db: AsyncSession) -> dict[str, datetime]:
    rows = await db.execute(
        select(AuditLog.object_id, AuditLog.created_at)
        .where(AuditLog.action == AUDIT_ACTION)
        .order_by(AuditLog.created_at)
    )
    return {str(obj): at for obj, at in rows.all()}


def _amount(value: Decimal) -> str:
    whole, _, frac = f"{value.quantize(Decimal('0.01')):f}".partition(".")
    sign = "−" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    grouped = " ".join([digits[max(0, i - 3) : i] for i in range(len(digits), 0, -3)][::-1])
    return f"{sign}{grouped},{frac} €"


def _day(value: date | None) -> str:
    return f"{value.day}. {value.month}. {value.year}" if value else "–"


def reminder_html(tone: Tone, invoices: list[IssuedInvoice], today: date) -> str:
    """E2: intro, table Faktúra · Splatnosť · Suma · Po splatnosti (dni), bold total row. Plain styles only."""
    paragraphs = [p.strip() for p in INTRO[tone].split("\n\n") if p.strip()]
    head = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    cell = 'style="border:1px solid #d0d5dd;padding:4px 8px;text-align:{a}"'
    rows = "".join(
        "<tr>"
        f"<td {cell.format(a='left')}>{html.escape(i.number)}</td>"
        f"<td {cell.format(a='left')}>{_day(i.due_on)}</td>"
        f"<td {cell.format(a='right')}>{_amount(i.remaining)}</td>"
        f"<td {cell.format(a='right')}>{(today - i.due_on).days if i.due_on else ''}</td>"
        "</tr>"
        for i in invoices
    )
    total = sum((i.remaining for i in invoices), Decimal("0"))
    table = (
        '<table style="border-collapse:collapse">'
        "<thead><tr>"
        f"<th {cell.format(a='left')}>Faktúra</th><th {cell.format(a='left')}>Splatnosť</th>"
        f"<th {cell.format(a='right')}>Suma</th><th {cell.format(a='right')}>Po splatnosti (dni)</th>"
        "</tr></thead>"
        f"<tbody>{rows}<tr><td {cell.format(a='left')}><b>Spolu</b></td><td {cell.format(a='left')}></td>"
        f"<td {cell.format(a='right')}><b>{_amount(total)}</b></td><td {cell.format(a='right')}></td></tr></tbody>"
        "</table>"
    )
    outro = "".join(f"<p>{html.escape(p)}</p>" for p in OUTRO.split("\n\n"))
    return head + table + outro


async def build_reminder_draft(
    db: AsyncSession,
    settings: Settings,
    bridge: BridgeClient,
    *,
    mailbox: Mailbox,
    account_id: uuid.UUID,
    person: Person | None,
    branch: Branch | None,
    debtor: Debtor,
    tone: Tone,
    today: date,
) -> ComposeDraft:
    """One draft per customer. Raises `InvoiceDraftError` (recipient / report / pdf) or `BridgeUnavailable`."""
    email = debtor.contact
    if email is None:
        raise InvoiceDraftError("no_contact")
    match = await match_sender(db, email, None, settings)
    if match.company is None or match.company.money_id != debtor.company.money_id or match.method not in STRONG:
        raise InvoiceDraftError("recipient_unconfirmed")
    invoices = debtor.invoices[:MAX_PER_REMINDER]
    reports = await load_reports(db)
    pdfs: list[tuple[str, bytes]] = []
    for inv in invoices:
        if inv.company_id != debtor.company.money_id:
            raise InvoiceDraftError("recipient_not_document_owner", inv.number)
        report_id = pick_report(reports, inv.kind, "sk")
        if report_id is None:
            raise InvoiceDraftError("report_not_configured", inv.number)
        data = await bridge.invoice_pdf(inv.kind, inv.id, report_id)
        if not data:
            raise InvoiceDraftError("pdf_missing", inv.number)
        pdfs.append((pdf_filename(inv.kind, inv.number), data))
    draft = await create_draft(
        db,
        settings,
        mailbox=mailbox,
        account_id=account_id,
        person=person,
        branch=branch,
        mode="new",
        user_html=reminder_html(tone, invoices, today),
    )
    draft.to_addrs = [{"name": debtor.company.name, "email": email}]
    draft.subject = SUBJECT[tone]
    prefix = storage_prefix(draft.id, debtor.company.money_id)
    for filename, data in pdfs:
        key, digest = storage.put_bytes(settings, data, prefix=prefix)
        db.add(
            ComposeAttachment(
                draft_id=draft.id,
                filename=filename,
                content_type="application/pdf",
                size=len(data),
                storage_key=key,
                sha256=digest,
                av_status="clean",
                is_inline=False,
            )
        )
    await db.flush()
    return draft
