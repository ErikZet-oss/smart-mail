"""#222 `delivery_note_attach`: a customer asks for an (issued) delivery note → reply draft with the PDF of Money's
own print report (`/pdfreport`, read only).

Same rules as `invoice_attach` (CLAUDE.md §7, §11): found without a model, the owner check (`Firma_ID` == the sender's
strongly matched company), another company's note only with the #215 tick and never in a batch, one company per draft,
every check again at approve and the recipients again at send (attachment marker). The print report is a per-branch
setting (11e, `branches.money_report_ids` keys `delivery_note` / `delivery_note_design`) chosen by the note's
`Stredisko_ID`; without any configured report the feature stays off.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.guards import check
from app.auth.models import Branch
from app.core.config import Settings
from app.money.bridge_client import BridgeClient
from app.money.invoice_attach import (
    ACK_CHECK,
    BODIES,
    MAX_PICK,
    ORDER_SUFFIX,
    STRONG,
    order_in,
    order_refs,
    order_search_terms,
)
from app.money.matching import match_sender
from app.money.models import MoneyCompany
from app.money.schemas import Delivery

SUGGESTION_TYPE = "delivery_note_attach"
DOCUMENT_KIND = "issued_delivery_note"
REPORT_KEY = "delivery_note"
DESIGN_KEY = "delivery_note_design"
BRANCH_KEYS: tuple[str, ...] = (REPORT_KEY, DESIGN_KEY)


@dataclass(frozen=True)
class BranchReport:
    branch_name: str
    report_id: str | None
    design_id: str | None


async def branch_reports(db: AsyncSession) -> dict[str, BranchReport]:
    """Branches by Money centre (lower-case GUID) with their delivery note report (None = not set)."""
    out: dict[str, BranchReport] = {}
    for branch in await db.scalars(select(Branch).where(Branch.money_centre_id.is_not(None))):
        ids = branch.money_report_ids or {}
        if branch.money_centre_id:
            out[branch.money_centre_id.strip().lower()] = BranchReport(
                branch_name=branch.name,
                report_id=str(ids.get(REPORT_KEY) or "") or None,
                design_id=str(ids.get(DESIGN_KEY) or "") or None,
            )
    return out


async def any_report(db: AsyncSession) -> bool:
    """The feature is active only when at least one branch has the delivery note report (#222 „Hotovo keď“)."""
    return any(r.report_id for r in (await branch_reports(db)).values())


def report_for(reports: dict[str, BranchReport], note: Delivery) -> BranchReport | None:
    return reports.get(str(note.centre_id).lower()) if note.centre_id else None


def pdf_filename(number: str) -> str:
    return f"Dodaci_list_{re.sub(r'[^A-Za-z0-9_-]+', '-', number).strip('-')}.pdf"


# ----- what the mail asks for (deterministic, no model) -----

# the words are case-insensitive, the abbreviation „DL“ only in capitals (never „dl“ = decilitre)
_DL_WORD = r"(?:(?i:dodac[íi]\w*\s+list\w*|lieferschein\w*|delivery\s+notes?)|\bDL\b)"
_WANTS = re.compile(_DL_WORD)
# „dodací list č. DV260042“, „DL 2026/0417“, „Lieferschein Nr. 4711-2026“ and a bare „DV260042“ / „DL-2600417“
_AFTER_WORD = re.compile(
    _DL_WORD + r"\s*(?i:č\.|c\.|číslo|cislo|no\.?|nr\.?|number|nummer|#|:)?\s*#?\s*"
    r"([A-Za-z]{0,4}[-/]?\d[\d/-]{3,14}\d)(?![\w/])"
)
_PREFIXED = re.compile(r"(?<![\w/])((?:DL|DV)[-/]?\d[\d/-]{3,14}\d)(?![\w/])")
# #222 „opravený / nový / správny dodací list“ (SK/CZ), „corrected / new delivery note“, „korrigierter Lieferschein“:
# a correction word anywhere in a delivery note request; „nový / new / neu / správny“ only right before the note word
_CORRECTED = re.compile(r"(?i:\b(?:oprav\w*|correct\w*|revised|amended|korrig\w*|berichtig\w*))")
_NEW_NOTE = re.compile(r"(?i:\b(?:nov[ýyéáo]\w*|spr[áa]vn\w*|new|neu\w*|richtig\w*)\W+(?:\w+\W+){0,2}?)" + _DL_WORD)
MAX_REFS = 5


def wants_delivery_note(text: str | None) -> bool:
    return bool(_WANTS.search(text or ""))


def delivery_refs(text: str | None) -> list[str]:
    """Delivery note numbers written in the mail, in order, without duplicates (spaces removed, upper case)."""
    found: list[tuple[int, str]] = [
        (m.start(1), m.group(1)) for rx in (_AFTER_WORD, _PREFIXED) for m in rx.finditer(text or "")
    ]
    out: list[str] = []
    for _, raw in sorted(found):
        ref = re.sub(r"\s+", "", raw).upper()
        if sum(c.isdigit() for c in ref) >= 4 and ref not in out:
            out.append(ref)
    return out[:MAX_REFS]


def asks_for_correction(text: str | None) -> bool:
    body = text or ""
    return wants_delivery_note(body) and bool(_CORRECTED.search(body) or _NEW_NOTE.search(body))


WHAT: dict[str, tuple[str, str]] = {
    "sk": ("dodací list", "dodacie listy"),
    "cs": ("dodací list", "dodací listy"),
    "en": ("delivery note", "delivery notes"),
    "de": ("den Lieferschein", "die Lieferscheine"),
}


def draft_body(language: str | None, numbers: list[str], orders: list[str] | None = None) -> str:
    lang = (language or "sk").lower()[:2]
    lang = lang if lang in BODIES else "sk"
    one, many = WHAT[lang]
    written = ", ".join(numbers)
    if orders:
        written += ORDER_SUFFIX[lang].format(orders=", ".join(orders))
    return BODIES[lang].format(what=one if len(numbers) == 1 else many, numbers=written)


# ----- the card: up to 5 notes, pre-selection, owner and branch report -----

Found = Literal["number", "order", "latest"]


@dataclass
class NoteItem:
    note: Delivery
    ref: str  # the number or order written in the mail ("" for the latest notes)
    how: Found
    own: bool
    exact: bool
    owner_name: str | None = None
    branch: str | None = None
    report_ok: bool = False

    @property
    def selected(self) -> bool:
        return self.own and self.exact and self.report_ok


@dataclass
class NotePick:
    email: str
    company_money_id: uuid.UUID | None
    company_name: str | None
    items: list[NoteItem] = field(default_factory=list)
    checks: list[dict[str, Any]] = field(default_factory=list)
    foreign: bool = False
    owner_money_id: uuid.UUID | None = None
    owner_name: str | None = None


def _newest(found: list[tuple[Delivery, str, Found]]) -> list[tuple[Delivery, str, Found]]:
    unique: dict[uuid.UUID, tuple[Delivery, str, Found]] = {}
    for row in found:
        unique.setdefault(row[0].id, row)
    rows = sorted(unique.values(), key=lambda r: (r[0].issued_on or date.min, r[0].number), reverse=True)
    return rows[:MAX_PICK]


async def find_notes(
    db: AsyncSession, settings: Settings, bridge: BridgeClient, *, email: str, text: str, body_text: str | None
) -> list[tuple[Delivery, str, Found]]:
    """Number in the mail → the customer's order in „Popis“ / „Poznámka“ → the latest notes of the sender's (strongly
    matched) company. Raises `BridgeUnavailable`."""
    match = await match_sender(db, email, body_text, settings)
    strong = match.company is not None and match.method in STRONG
    found: list[tuple[Delivery, str, Found]] = []
    for ref in delivery_refs(text):
        result = await bridge.search_deliveries(number=ref)
        found.extend((d, ref, "number") for d in result.items if d.number.upper() == ref)
    if not found:
        for order in order_refs(text):
            for term in order_search_terms(order):
                result = await bridge.search_deliveries(order=term)
                found.extend((d, order, "order") for d in result.items)
    if not found and strong and match.company is not None:
        result = await bridge.search_deliveries(company_id=match.company.money_id)
        found.extend((d, "", "latest") for d in result.items if d.company_id == match.company.money_id)
    return found


async def pick_notes(
    db: AsyncSession, settings: Settings, *, email: str, body_text: str | None, found: list[tuple[Delivery, str, Found]]
) -> NotePick:
    match = await match_sender(db, email, body_text, settings)
    strong = match.company is not None and match.method in STRONG
    out = NotePick(
        email=email,
        company_money_id=match.company.money_id if match.company else None,
        company_name=match.company.name if match.company else None,
    )
    reports = await branch_reports(db)
    names: dict[uuid.UUID, str | None] = {}
    for note, ref, how in _newest(found):
        own = strong and note.company_id is not None and note.company_id == out.company_money_id
        owner_name = None
        if not own and note.company_id is not None:
            if note.company_id not in names:
                company = await db.scalar(select(MoneyCompany).where(MoneyCompany.money_id == note.company_id))
                names[note.company_id] = company.name if company else None
            owner_name = names[note.company_id]
        exact = (how == "number") or (how == "order" and (order_in(note.description, ref) or order_in(note.note, ref)))
        branch = report_for(reports, note)
        out.items.append(
            NoteItem(
                note=note,
                ref=ref,
                how=how,
                own=own,
                exact=exact,
                owner_name=owner_name,
                branch=branch.branch_name if branch else None,
                report_ok=bool(branch and branch.report_id),
            )
        )
    if out.items and not any(i.report_ok for i in out.items):
        first = out.items[0]
        out.checks.append(check("delivery_note_report_missing", "blocking", branch=first.branch or "—"))
    owners = {i.note.company_id for i in out.items if not i.own}
    if not any(i.own for i in out.items) and len(owners) == 1 and None not in owners:
        owner = next(iter(owners))
        out.foreign, out.owner_money_id = True, owner
        out.owner_name = names.get(owner) if owner else None
        out.checks.append(
            check(
                ACK_CHECK,
                "requires_ack",
                owner=out.owner_name or "",
                requester=out.company_name or email,
                numbers=[i.note.number for i in out.items],
            )
        )
    elif not strong:
        out.checks.append(check("recipient_unconfirmed", "blocking", email=email))
    return out


def note_json(item: NoteItem) -> dict[str, Any]:
    n = item.note
    return {
        "id": str(n.id),
        "kind": "delivery_note",
        "number": n.number,
        "issued_on": n.issued_on.isoformat() if n.issued_on else None,
        "due_on": None,
        "total": str(n.total),
        "remaining": str(n.total),
        "order": item.ref if item.how == "order" else None,
        "own": item.own,
        "exact": item.exact,
        "selected": item.selected,
        "owner_money_id": str(n.company_id) if n.company_id and not item.own else None,
        "owner_name": item.owner_name,
        "branch": item.branch,
        "report_ok": item.report_ok,
    }
