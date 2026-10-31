"""Phase 3d `invoice_attach`: a customer asks for an invoice copy → reply draft with the original Money PDF.

Rules (CLAUDE.md §7, §11; MONEY_API §5.1; DOCUMENTS_SPEC §6):
- Invoice references are found in the mail without a model (deterministic, no cost) and looked up in Money.
- **Blocking: the invoice belongs to the company of the recipient** (`Firma_ID` == the matched company). The recipient
  must be matched strongly (confirmed link, Money person, company e-mail) — an IČO or domain guess is not enough.
- One customer per draft. The PDF is always Money's own report (13b report id per language), never rendered here.
- Never sends: approve / „Poslať“ create a reply draft in Koncepty (autonomy level 2). Every check runs again at
  approve, and the recipients are checked again **at send** (attachment marker in the storage key), so changing the
  recipient in W4 cannot mail an invoice to another company.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.guards import check
from app.ai.models import OrgSettings
from app.auth.models import Branch
from app.core.config import Settings
from app.money.bridge_client import BridgeClient, BridgeUnavailable
from app.money.matching import match_sender
from app.money.schemas import IssuedInvoice

SUGGESTION_TYPE = "invoice_attach"
SECTION_REPORTS = "money.reports"
MARKER = "money-invoice"
STRONG = frozenset({"confirmed", "person", "company_email"})
MAX_REFS = 5
ReportKind = Literal["invoice", "proforma"]
ReportLang = Literal["sk", "en", "de"]
REPORT_KINDS: tuple[ReportKind, ...] = ("invoice", "proforma")
REPORT_LANGS: tuple[ReportLang, ...] = ("sk", "en", "de")
_REPORT_ID = re.compile(r"^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|\d{1,9})$")
# „FV2600042“, „ZF 26/0815“, „faktúra č. 2026/0815“, „VS 2600042“ — a reference needs 4+ digits
_PREFIXED = re.compile(r"\b(?:FV|FA|ZF|ZFV|VF)\s?[-/]?\s?\d[\d/-]{3,14}\d\b", re.IGNORECASE)
_AFTER_WORD = re.compile(
    r"(?:fakt[úu]r[auy]?|faktúry|invoice|rechnung|z[áa]lohov[áa]\s+fakt[úu]ra|vs|variabiln[ýy]\s+symbol)"
    r"\s*(?:č\.|c\.|číslo|cislo|no\.?|nr\.?|:)?\s*([A-Z]{0,3}\s?\d[\d/-]{3,14}\d)",
    re.IGNORECASE,
)

BODIES: dict[str, str] = {
    "sk": "Dobrý deň,\n\nv prílohe Vám posielame {what} {numbers}.\n\nS pozdravom",
    "cs": "Dobrý den,\n\nv příloze Vám zasíláme {what} {numbers}.\n\nS pozdravem",
    "en": "Hello,\n\nplease find attached {what} {numbers}.\n\nKind regards",
    "de": "Guten Tag,\n\nim Anhang senden wir Ihnen {what} {numbers}.\n\nMit freundlichen Grüßen",
}
WHAT: dict[str, tuple[str, str]] = {
    "sk": ("kópiu faktúry", "kópie faktúr"),
    "cs": ("kopii faktury", "kopie faktur"),
    "en": ("a copy of invoice", "copies of invoices"),
    "de": ("eine Kopie der Rechnung", "Kopien der Rechnungen"),
}


def invoice_refs(text: str | None) -> list[str]:
    """Invoice numbers / variable symbols written in the mail, in order, without duplicates."""
    found: list[str] = []
    for m in _PREFIXED.finditer(text or ""):
        found.append(m.group(0))
    for m in _AFTER_WORD.finditer(text or ""):
        found.append(m.group(1))
    out: list[str] = []
    seen: set[str] = set()
    for raw in found:
        ref = re.sub(r"\s+", "", raw).upper()
        if ref not in seen and sum(c.isdigit() for c in ref) >= 4:
            seen.add(ref)
            out.append(ref)
    return out[:MAX_REFS]


def report_language(language: str | None) -> ReportLang:
    lang = (language or "sk").lower()[:2]
    return "en" if lang == "en" else "de" if lang == "de" else "sk"  # cs and others → the Slovak report


def report_id_valid(value: str) -> bool:
    return bool(_REPORT_ID.match(value))


async def load_reports(db: AsyncSession) -> dict[str, dict[str, str]]:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_REPORTS))
    data = row.data if row else {}
    return {kind: {lang: str((data.get(kind) or {}).get(lang) or "") for lang in REPORT_LANGS} for kind in REPORT_KINDS}


def pick_report(reports: dict[str, dict[str, str]], kind: str, language: str | None) -> str | None:
    """13b: the report of the customer's language; an empty language falls back to SK."""
    per_kind = reports.get(kind) or {}
    return per_kind.get(report_language(language)) or per_kind.get("sk") or None


async def load_branch_reports(db: AsyncSession) -> dict[str, dict[str, str]]:
    """#174: branch reports by Money centre id (lower-case GUID) — only branches with a centre and a report."""
    out: dict[str, dict[str, str]] = {}
    for branch in await db.scalars(select(Branch).where(Branch.money_centre_id.is_not(None))):
        ids: dict[str, str] = {
            str(k): str(v) for k, v in (branch.money_report_ids or {}).items() if k in REPORT_KINDS and v
        }
        if ids and branch.money_centre_id:
            out[branch.money_centre_id.strip().lower()] = ids
    return out


def report_for_invoice(
    reports: dict[str, dict[str, str]],
    branch_reports: dict[str, dict[str, str]],
    inv: IssuedInvoice,
    language: str | None,
) -> str | None:
    """#174: the branch of the invoice = the branch whose centre is the invoice's `Stredisko_ID`.
    SK (or empty language) → branch report, else company SK (13b). EN/DE → company report of that language, else the
    branch report (SK), else company SK. No centre / no branch → 13b as before. None → `report_not_configured`."""
    branch = branch_reports.get(str(inv.centre_id).lower()) if inv.centre_id else None
    own = (branch or {}).get(inv.kind) or None
    lang = report_language(language)
    company = reports.get(inv.kind) or {}
    if lang == "sk":
        return own or company.get("sk") or None
    return company.get(lang) or own or company.get("sk") or None


def draft_body(language: str | None, numbers: list[str]) -> str:
    lang = (language or "sk").lower()[:2]
    lang = lang if lang in BODIES else "sk"
    one, many = WHAT[lang]
    return BODIES[lang].format(what=one if len(numbers) == 1 else many, numbers=", ".join(numbers))


@dataclass
class Evaluation:
    email: str
    company_money_id: uuid.UUID | None
    company_name: str | None
    invoices: list[IssuedInvoice] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(c["level"] == "blocking" for c in self.checks)


async def evaluate(
    db: AsyncSession,
    settings: Settings,
    bridge: BridgeClient,
    *,
    email: str,
    body_text: str | None,
    refs: list[str],
    language: str | None,
) -> Evaluation:
    """Live checks against Money for one recipient and the requested invoice numbers. Raises `BridgeUnavailable`."""
    match = await match_sender(db, email, body_text, settings)
    out = Evaluation(
        email=email,
        company_money_id=match.company.money_id if match.company else None,
        company_name=match.company.name if match.company else None,
    )
    if match.company is None or match.method not in STRONG:
        out.checks.append(check("recipient_unconfirmed", "blocking", email=email))
    reports = await load_reports(db)
    branch_reports = await load_branch_reports(db)
    for ref in refs:
        found = await bridge.search_invoices(number=ref)
        if not found.items and any(c.isdigit() for c in ref):
            found = await bridge.search_invoices(vs="".join(c for c in ref if c.isdigit()))
        if not found.items:
            out.checks.append(check("invoice_not_found", "warning", number=ref))
            continue
        for inv in found.items[:1]:  # one document per written number
            if out.company_money_id is None or inv.company_id != out.company_money_id:
                # never name the other company or its amounts on the card
                out.checks.append(check("recipient_not_document_owner", "blocking", number=inv.number))
                continue
            if inv.id in {i.id for i in out.invoices}:
                continue
            out.invoices.append(inv)
            if report_for_invoice(reports, branch_reports, inv, language) is None:
                out.checks.append(check("report_not_configured", "blocking", kind=inv.kind))
    if not out.invoices:
        out.checks.append(check("no_invoice", "blocking"))
    else:
        out.checks.append(check("invoice_owner_ok", "ok", count=len(out.invoices)))
    return out


def invoice_json(inv: IssuedInvoice) -> dict[str, Any]:
    return {
        "id": str(inv.id),
        "kind": inv.kind,
        "number": inv.number,
        "due_on": inv.due_on.isoformat() if inv.due_on else None,
        "total": str(inv.total),
        "remaining": str(inv.remaining),
    }


def storage_prefix(draft_id: uuid.UUID, company_money_id: uuid.UUID) -> str:
    """The marker the send check reads: `compose/<draft>/money-invoice/<company>`."""
    return f"compose/{draft_id}/{MARKER}/{company_money_id}"


def marked_company(storage_key: str) -> uuid.UUID | None:
    parts = storage_key.split("/")
    try:
        i = parts.index(MARKER)
        return uuid.UUID(parts[i + 1])
    except (ValueError, IndexError):
        return None


async def recipient_block(
    db: AsyncSession, settings: Settings, recipients: list[str], storage_keys: list[str]
) -> str | None:
    """At send: every external recipient of a draft with a Money invoice must belong to that invoice's company.
    Returns the first offending address (or the company marker problem), else None."""
    companies = {c for c in (marked_company(k) for k in storage_keys) if c is not None}
    if not companies:
        return None
    if len(companies) > 1:
        return "several_companies"  # one customer per message
    company = next(iter(companies))
    for email in recipients:
        email = email.strip().lower()
        if not email or settings.is_internal_address(email):
            continue
        match = await match_sender(db, email, None, settings)
        if match.company is None or match.company.money_id != company or match.method not in STRONG:
            return email
    return None


def total_remaining(invoices: list[IssuedInvoice]) -> Decimal:
    return sum((i.remaining for i in invoices), Decimal("0"))


__all__ = [
    "SUGGESTION_TYPE",
    "BridgeUnavailable",
    "Evaluation",
    "draft_body",
    "evaluate",
    "invoice_refs",
    "load_branch_reports",
    "load_reports",
    "pick_report",
    "recipient_block",
    "report_for_invoice",
    "storage_prefix",
]
