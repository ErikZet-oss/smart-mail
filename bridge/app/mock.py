"""Mock Money backend (MONEY_BACKEND=mock, MONEY_API §8) — Phase 3 part of the seed.

ALL DATA IS FICTIONAL: companies on `*.example` domains, IČO with a deliberately wrong mod-11 check digit, generated
document numbers. Deterministic (fixed seed and anchor date) so tests and screenshots are stable.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.backend import InvoiceQuery
from app.models import (
    Activity,
    CodebookItem,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Connection,
    Delivery,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    MatchedBy,
    Order,
    Person,
    PersonPage,
)

NS = uuid.UUID("5a1d0b5e-0000-4000-8000-000000000000")
ANCHOR = date(2026, 10, 1)  # documents are dated before this day
SEEDED_AT = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
CUSTOMERS = 20
INVOICES = 300
PROFORMAS = 20
FIRST_NAMES = ["Ján", "Mária", "Peter", "Eva", "Tomáš", "Zuzana", "Martin", "Jana", "Lukáš", "Katarína"]
LAST_NAMES = ["Fiktívny", "Testovacia", "Ukážkový", "Vzorová", "Príkladný", "Modelová"]
FUNCTIONS = ["nákup", "konateľ", "účtovníčka", "sklad", None]


def mid(kind: str, n: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"{kind}:{n}")


def fake_ico(rng: random.Random) -> str:
    """8 digits whose mod-11 check digit is deliberately wrong, so it can never be a real Slovak IČO."""
    digits = [rng.randint(0, 9) for _ in range(7)]
    total = sum(d * w for d, w in zip(digits, range(8, 1, -1), strict=True))
    check = (11 - total % 11) % 10
    return "".join(map(str, digits)) + str((check + 1) % 10)


def minimal_pdf(text: str) -> bytes:
    """A valid one-page PDF with one ASCII line (xref offsets computed)."""
    safe = text.encode("ascii", "replace").decode().replace("\\", "").replace("(", "").replace(")", "")
    stream = f"BT /F1 14 Tf 72 760 Td ({safe}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


@dataclass
class MockData:
    companies: list[Company] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    invoices: list[IssuedInvoice] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    deliveries: list[Delivery] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)
    codebooks: dict[str, list[CodebookItem]] = field(default_factory=dict)


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / Decimal(100)


def build(seed: int = 20261030) -> MockData:
    rng = random.Random(seed)  # noqa: S311 — fictional test data, not security
    data = MockData()
    eur = mid("currency", 1)
    data.codebooks = {
        "warehouses": [
            CodebookItem(id=mid("warehouse", 1), code="SKL-A", name="Sklad A (fiktívny)"),
            CodebookItem(id=mid("warehouse", 2), code="SKL-B", name="Sklad B (fiktívny)"),
        ],
        "centres": [
            CodebookItem(id=mid("centre", i), code=f"STR{i}", name=f"Stredisko {i} (fiktívne)") for i in (1, 2, 3)
        ],
        "numerical-series": [
            CodebookItem(id=mid("series", 1), code="FV", name="Faktúry vydané (fiktívne)"),
            CodebookItem(id=mid("series", 2), code="OP", name="Objednávky prijaté (fiktívne)"),
        ],
        "currencies": [
            CodebookItem(id=eur, code="EUR", name="Euro"),
            CodebookItem(id=mid("currency", 2), code="CZK", name="Česká koruna"),
        ],
    }
    for c in range(1, CUSTOMERS + 1):
        domain = f"firma{c:02d}.example"
        company = Company(
            id=mid("company", c),
            code=f"F{c:04d}",
            name=f"Fiktívna firma {c:02d} s.r.o.",
            ico=fake_ico(rng),
            dic=None,
            icdph=None,
            email=f"info@{domain}",
            discount_pct=Decimal(rng.choice([0, 0, 3, 5, 10])),
            own_discount=c % 4 == 0,
            due_days=rng.choice([14, 14, 30, 60]),
            connections=[
                Connection(kind="E-mail", value=f"faktury@{domain}"),
                Connection(kind="Telefón", value=f"+421 900 {c:03d} {c:03d}"),
            ],
        )
        data.companies.append(company)
        for p in range(1, rng.randint(1, 3) + 1):
            first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
            local = f"{first[0]}.{last}".lower().encode("ascii", "ignore").decode()
            data.persons.append(
                Person(
                    id=mid("person", c * 10 + p),
                    company_id=company.id,
                    first_name=first,
                    last_name=last,
                    name=f"{first} {last}",
                    function=rng.choice(FUNCTIONS),
                    email=f"{local}{p}@{domain}",
                    phone=None,
                )
            )
    for n in range(1, INVOICES + PROFORMAS + 1):
        kind: InvoiceKind = "invoice" if n <= INVOICES else "proforma"
        company = data.companies[rng.randrange(CUSTOMERS)]
        issued = ANCHOR - timedelta(days=rng.randint(1, 540))
        due = issued + timedelta(days=company.due_days or 14)
        total = _money(rng, 20, 4000)
        paid = rng.random() < 0.8 and due < ANCHOR - timedelta(days=5)
        partial = not paid and rng.random() < 0.15
        remaining = Decimal("0") if paid else (total / 2).quantize(Decimal("0.01")) if partial else total
        prefix = "FV" if kind == "invoice" else "ZF"
        data.invoices.append(
            IssuedInvoice(
                id=mid(kind, n),
                kind=kind,
                number=f"{prefix}{issued.year % 100:02d}{n:05d}",
                variable_symbol=f"{issued.year % 100:02d}{n:06d}",
                company_id=company.id,
                issued_on=issued,
                due_on=due,
                paid_on=due - timedelta(days=rng.randint(0, 10)) if paid else None,
                total=total,
                remaining=remaining,
                currency_id=eur,
                reference=f"PO-{n:04d}" if rng.random() < 0.3 else None,
                doc_type=0,
            )
        )
    for n in range(1, 61):
        company = data.companies[rng.randrange(CUSTOMERS)]
        issued = ANCHOR - timedelta(days=rng.randint(1, 300))
        data.orders.append(
            Order(
                id=mid("order", n),
                number=f"OP{issued.year % 100:02d}{n:04d}",
                company_id=company.id,
                issued_on=issued,
                reference=f"OBJ-{n:04d}",
                state=rng.choice([0, 1, 2]),
                done=rng.choice([0, 1]),
                total=_money(rng, 50, 3000),
            )
        )
        data.deliveries.append(
            Delivery(
                id=mid("delivery", n),
                number=f"DV{issued.year % 100:02d}{n:04d}",
                company_id=company.id,
                issued_on=issued + timedelta(days=2),
                moved_on=issued + timedelta(days=2),
                reference=f"OBJ-{n:04d}",
                state=rng.choice([0, 1]),
                transport=rng.choice(["Kuriér (fiktívny)", "Osobný odber", None]),
                total=_money(rng, 50, 3000),
            )
        )
    for n in range(1, 41):
        company = data.companies[rng.randrange(CUSTOMERS)]
        data.activities.append(
            Activity(
                id=mid("activity", n),
                company_id=company.id,
                person_id=None,
                type_id=mid("activity-type", 1),
                description=rng.choice(["E-mail odoslaný (fiktívny)", "Telefonát (fiktívny)", "Upomienka (fiktívna)"]),
                started_at=SEEDED_AT - timedelta(days=rng.randint(1, 200)),
                done=True,
            )
        )
    return data


def _newest_first[T: (IssuedInvoice, Order, Delivery)](items: list[T]) -> list[T]:
    return sorted(items, key=lambda i: (i.issued_on or date.min, i.number), reverse=True)


class MockBackend:
    def __init__(self, data: MockData | None = None) -> None:
        self.data = data or build()

    async def aclose(self) -> None:
        return None

    async def version(self) -> str:
        return "mock"

    @staticmethod
    def _changed(since: datetime | None) -> bool:
        return since is None or since < SEEDED_AT

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage:
        rows = self.data.companies if self._changed(since) else []
        page = rows[start : start + count]
        return CompanyPage(items=page, next_from=start + count if start + count < len(rows) else None)

    async def company(self, company_id: uuid.UUID) -> Company | None:
        return next((c for c in self.data.companies if c.id == company_id), None)

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage:
        rows = self.data.persons if self._changed(since) else []
        page = rows[start : start + count]
        return PersonPage(items=page, next_from=start + count if start + count < len(rows) else None)

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage:
        rows = self.data.codebooks[name]
        page = rows[start : start + count]
        return CodebookPage(items=page, next_from=start + count if start + count < len(rows) else None)

    async def search_invoices(self, query: InvoiceQuery) -> InvoiceSearch:
        inv = self.data.invoices
        digits = "".join(c for c in (query.number or "") if c.isdigit())
        steps: list[tuple[MatchedBy, bool, Callable[[IssuedInvoice], bool]]] = [
            ("number", bool(query.number), lambda i: i.number == query.number),
            ("variable_symbol", bool(query.variable_symbol), lambda i: i.variable_symbol == query.variable_symbol),
            ("reference", bool(query.reference), lambda i: i.reference == query.reference),
            (
                "company_dates",
                bool(query.company_id and query.date_from and query.date_to),
                lambda i: (
                    i.company_id == query.company_id
                    and i.issued_on is not None
                    and query.date_from is not None
                    and query.date_to is not None
                    and query.date_from <= i.issued_on <= query.date_to
                ),
            ),
            ("number_digits", bool(digits and digits != query.number), lambda i: digits in i.number),
        ]
        for matched_by, active, pred in steps:
            if active:
                found = _newest_first([i for i in inv if pred(i)])[:20]
                if found:
                    return InvoiceSearch(matched_by=matched_by, items=found)
        return InvoiceSearch(matched_by="none", items=[])

    async def receivables(self, company_id: uuid.UUID) -> list[IssuedInvoice]:
        return _newest_first([i for i in self.data.invoices if i.company_id == company_id and i.remaining > 0])

    async def orders(self, company_id: uuid.UUID, since: date) -> list[Order]:
        rows = [o for o in self.data.orders if o.company_id == company_id and o.issued_on and o.issued_on >= since]
        return _newest_first(rows)

    async def deliveries(self, company_id: uuid.UUID, since: date) -> list[Delivery]:
        rows = [d for d in self.data.deliveries if d.company_id == company_id and d.issued_on and d.issued_on >= since]
        return _newest_first(rows)

    async def activities(self, company_id: uuid.UUID) -> list[Activity]:
        rows = [a for a in self.data.activities if a.company_id == company_id]
        return sorted(rows, key=lambda a: a.started_at or SEEDED_AT, reverse=True)

    async def invoice_pdf(self, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        inv = next((i for i in self.data.invoices if i.id == invoice_id and i.kind == kind), None)
        if inv is None:
            return None
        return minimal_pdf(f"FIKTIVNY DOKLAD {inv.number} - Smart Mail mock")
