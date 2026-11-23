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

from app import wildcard
from app.backend import ArticleQuery, CatalogExists, DeliveryQuery, DuplicateNote, InvoiceQuery
from app.models import (
    Activity,
    ActivityIn,
    ActivityOut,
    Article,
    ArticleCreated,
    ArticleCreateIn,
    ArticleUnit,
    CodebookItem,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Connection,
    Delivery,
    DeliveryMatchedBy,
    DeliveryNoteCreated,
    DeliveryNoteIn,
    DeliveryNoteTemplate,
    DeliverySearch,
    DocumentKind,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    MatchedBy,
    Order,
    OverduePage,
    Person,
    PersonPage,
    ReceivedNoteRow,
    SupplierCode,
    SupplierCodePage,
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
    articles: list[Article] = field(default_factory=list)
    supplier_codes: list[SupplierCode] = field(default_factory=list)
    received_notes: list[dict[str, object]] = field(default_factory=list)  # #247: Money-shaped raw rows


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
        "activity-types": [
            CodebookItem(id=mid("activity-type", 1), code="EMAIL", name="E-mail odoslaný (fiktívny typ)"),
            CodebookItem(id=mid("activity-type", 2), code="UPOM", name="Upomienka (fiktívny typ)"),
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
                centre_id=None if n % 7 == 0 else mid("centre", n % 3 + 1),  # no rng: keeps the seed stable
                # #210: every 4th invoice comes from a (fictional) e-shop order, number in „Popis“; no rng
                description=f"Objednávka {2410000000 + n}" if n % 4 == 0 else None,
                # #217: some invoices carry the customer's order (with letters) only in „Poznámka“; no rng
                note=f"Vaša objednávka OR{6024000 + n:08d}" if n % 6 == 3 else None,
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
                # #222 (no rng: keeps the seed stable): branch centre and the customer's order in Popis / Poznámka
                centre_id=None if n % 7 == 0 else mid("centre", n % 3 + 1),
                description=f"Objednávka OR{6024000 + n:08d}" if n % 3 == 0 else None,
                note=f"Vaša objednávka {2410100000 + n}" if n % 5 == 0 else None,
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
    _articles(data)
    _variants(data)
    for n in (1, 2):  # #247 one person-made received delivery note per centre 1 and 2 = the branch templates
        data.received_notes.append(received_template(n, mid("centre", n), data.companies[0], data.articles[0]))
    return data


# (our code, catalog, name, EAN, supplier code of company 1, unit of supplier code + its size in pieces)
_ARTICLES = [
    ("ART-0001", "933-8-30-ZN", "Skrutka DIN 933 M8x30 8.8 Zn (fiktívna)", "8590000000017", "D933-830", ("ks", 1)),
    ("ART-0002", "933-10-30-A2", "Skrutka DIN 933 M10x30 A2 (fiktívna)", "8590000000024", "933-10-30-A2", ("ks", 1)),
    ("ART-0003", "934-10-A2", "Matica DIN 934 M10 A2 (fiktívna)", "8590000000031", "934-10-A2", ("bal", 200)),
    ("ART-0004", "125-8-ZN", "Podložka DIN 125 M8 Zn (fiktívna)", "8590000000048", "125-8-ZN", ("bal", 500)),
    ("ART-0005", "912-6-20-ZN", "Skrutka DIN 912 M6x20 Zn (fiktívna)", "8590000000055", None, None),
    ("ART-0006", "1481-6-40", "Kolík DIN 1481 6x40 (fiktívny)", None, "K1481-640", ("ks", 1)),
]


def _variants(data: MockData) -> None:
    """#233 a fictional main card with three size variants (catalog = main catalog + size suffix)."""
    main = Article(
        id=mid("article", 100), code="ART-0100", catalog="9990100", name="Vrut fiktívny (hlavná)", ean=None, unit="ks"
    )
    data.articles.append(main)
    for n, size in enumerate(("0006", "0010", "0016"), start=1):
        data.articles.append(
            Article(
                id=mid("article", 100 + n),
                code=f"ART-0100-{size}",
                catalog=f"9990100{size}",
                name=f"Vrut fiktívny {int(size)} mm",
                ean=None,
                unit="ks",
                parent_id=main.id,
            )
        )


def _articles(data: MockData) -> None:
    supplier = data.companies[0].id  # a fictional company is also a supplier in the mock
    for n, (code, catalog, name, ean, sup_code, sup_unit) in enumerate(_ARTICLES, start=1):
        units = [ArticleUnit(code="ks", qty=Decimal("1"), decimals=0)]
        if sup_unit and sup_unit[0] == "bal":
            units.append(ArticleUnit(code="bal", qty=Decimal(sup_unit[1]), decimals=0))
        article = Article(
            id=mid("article", n), code=code, catalog=catalog, name=name, ean=ean, unit="ks", units=units, inactive=False
        )
        data.articles.append(article)
        if sup_code and sup_unit:
            data.supplier_codes.append(
                SupplierCode(
                    id=mid("article-supplier", len(data.supplier_codes) + 1),
                    article_id=article.id,
                    supplier_id=supplier,
                    code=sup_code,
                    name=name.replace(" (fiktívna)", "").replace(" (fiktívny)", ""),
                    last_price=Decimal("0.0840") if sup_unit[0] == "ks" else Decimal("8.0500"),
                    unit=sup_unit[0],
                    article_unit=sup_unit[0],
                    article_unit_qty=Decimal(sup_unit[1]),
                )
            )


def received_template(n: int, centre: uuid.UUID, supplier: Company, article: Article) -> dict[str, object]:
    """#247 a received delivery note made by a person in Money — the branch template (fictional IDs from `mid`)."""
    return {
        "ID": str(mid("received-note", n)),
        "Deleted": False,
        "CisloDokladu": f"DLP{n:04d}/2026",
        "Nazev": "Príjem tovaru (fiktívny)",
        "Odkaz": f"DL-FIKT-{n:03d}",
        "Poznamka": "",
        "Faze": 1,
        "Schvaleno": True,
        "DatumVystaveni": f"2026-11-{10 + n:02d}T00:00:00",
        "Create_Date": f"2026-11-{10 + n:02d}T08:00:00",
        "Firma_ID": str(supplier.id),
        "Firma": {"Nazev": supplier.name},
        "AdresaNazev": supplier.name,
        "Stredisko_ID": str(centre),
        "CiselnaRada_ID": str(mid("series", 3)),
        "DruhPohybu_ID": str(mid("movement-kind", 1)),
        "DruhSkladovehoPohybu_ID": str(mid("stock-movement-kind", 1)),
        "Predkontace_ID": str(mid("account-assignment", 1)),
        "RegistraceDPH_ID": str(mid("vat-registration", 1)),
        "DruhDokladu_ID": str(mid("document-kind", 1)),
        "Group_ID": str(mid("note-group", n)),
        "Mena_ID": str(mid("currency", 1)),
        "SumaZaklad": Decimal("8.40"),
        "CelkovaCastka": Decimal("10.33"),
        "Polozky": [
            {
                "ID": str(mid("received-note-item", n)),
                "CisloPolozky": 1,
                "Poradi": 1,
                "Mnozstvi": Decimal("100"),
                "JednCena": Decimal("0.0840"),
                "TypObsahu": 1,
                "TypCeny": 0,
                "DruhSazbyDPH": 2,
                "SazbaDPH_ID": str(mid("vat-rate", 23)),
                "DruhPolozky_ID": str(mid("item-kind", 1)),
                "Stredisko_ID": str(centre),
                "ObsahPolozky": {
                    "Artikl_ID": str(article.id),
                    "Sklad_ID": str(mid("warehouse", 1)),
                    "VazbaTypVazby": 0,
                },
            },
            {
                "ID": str(mid("received-note-item", 100 + n)),
                "Poradi": 2,
                "Mnozstvi": Decimal("1"),
                "JednCena": Decimal("0"),
                "TypObsahu": 0,
                "Nazev": "Text",
                "ObsahPolozky": None,
            },
        ],
    }


def _newest_first[T: (IssuedInvoice, Order, Delivery)](items: list[T]) -> list[T]:
    return sorted(items, key=lambda i: (i.issued_on or date.min, i.number), reverse=True)


class MockBackend:
    def __init__(self, data: MockData | None = None) -> None:
        self.data = data or build()
        self.smids: dict[uuid.UUID, str] = {}
        self.article_smids: dict[uuid.UUID, str] = {}  # D32: SMID of every created article

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
            (
                "order",
                bool(query.order),
                lambda i: (
                    query.order is not None
                    and (query.order in (i.description or "") or query.order in (i.note or ""))
                    and (query.company_id is None or i.company_id == query.company_id)
                ),
            ),
        ]
        for matched_by, active, pred in steps:
            if active:
                limit = 200 if matched_by == "company_dates" else 20  # as the API backend (HISTORY_LIMIT)
                found = _newest_first([i for i in inv if pred(i)])[:limit]
                if found:
                    return InvoiceSearch(matched_by=matched_by, items=found)
        return InvoiceSearch(matched_by="none", items=[])

    async def receivables(self, company_id: uuid.UUID) -> list[IssuedInvoice]:
        return _newest_first([i for i in self.data.invoices if i.company_id == company_id and i.remaining > 0])

    async def overdue(self, before: date, start: int, count: int) -> OverduePage:
        rows = [
            i
            for i in self.data.invoices
            if i.kind == "invoice" and i.remaining > 0 and i.due_on is not None and i.due_on < before
        ]
        page = rows[start : start + count]
        return OverduePage(items=page, next_from=start + count if start + count < len(rows) else None)

    async def orders(self, company_id: uuid.UUID, since: date) -> list[Order]:
        rows = [o for o in self.data.orders if o.company_id == company_id and o.issued_on and o.issued_on >= since]
        return _newest_first(rows)

    async def deliveries(self, company_id: uuid.UUID, since: date) -> list[Delivery]:
        rows = [d for d in self.data.deliveries if d.company_id == company_id and d.issued_on and d.issued_on >= since]
        return _newest_first(rows)

    async def activities(self, company_id: uuid.UUID) -> list[Activity]:
        rows = [a for a in self.data.activities if a.company_id == company_id]
        return sorted(rows, key=lambda a: a.started_at or SEEDED_AT, reverse=True)

    async def create_activity(self, activity: ActivityIn) -> ActivityOut:
        """Idempotent by SMID: a repeat returns the activity that already exists."""
        for existing, smid in self.smids.items():
            if smid == activity.smid:
                return ActivityOut(id=existing, created=False)
        new = Activity(
            id=uuid.uuid4(),
            company_id=activity.company_id,
            person_id=None,
            type_id=activity.type_id,
            description=f"{activity.subject} {activity.description}".strip()[:300],
            started_at=datetime.now(UTC),
            done=True,
        )
        self.data.activities.append(new)
        self.smids[new.id] = activity.smid
        return ActivityOut(id=new.id, created=True)

    async def search_deliveries(self, query: DeliveryQuery) -> DeliverySearch:
        rows = self.data.deliveries
        steps: list[tuple[DeliveryMatchedBy, bool, Callable[[Delivery], bool]]] = [
            ("number", bool(query.number), lambda d: d.number == query.number),
            (
                "order",
                bool(query.order),
                lambda d: (
                    query.order is not None
                    and (query.order in (d.description or "") or query.order in (d.note or ""))
                    and (query.company_id is None or d.company_id == query.company_id)
                ),
            ),
            (
                "company",
                bool(query.company_id and not query.number and not query.order),
                lambda d: d.company_id == query.company_id,
            ),
        ]
        for matched_by, active, pred in steps:
            if active:
                found = _newest_first([d for d in rows if pred(d)])[: 200 if matched_by == "company" else 20]
                if found:
                    return DeliverySearch(matched_by=matched_by, items=found)
        return DeliverySearch(matched_by="none", items=[])

    async def document_pdf(
        self, kind: DocumentKind, record_id: uuid.UUID, report_id: str, design_id: str | None
    ) -> bytes | None:
        note = next((d for d in self.data.deliveries if d.id == record_id), None)
        if note is None:
            return None
        return minimal_pdf(f"FIKTIVNY DODACI LIST {note.number} - Smart Mail mock")

    async def invoice_pdf(self, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        inv = next((i for i in self.data.invoices if i.id == invoice_id and i.kind == kind), None)
        if inv is None:
            return None
        return minimal_pdf(f"FIKTIVNY DOKLAD {inv.number} - Smart Mail mock")

    # ----- Phase 4b (read-only) -----

    async def articles(self, query: ArticleQuery) -> list[Article]:
        rows = self.data.articles
        if query.ean:
            found = [a for a in rows if a.ean == query.ean]
        elif query.code:
            found = [a for a in rows if query.code in (a.code, a.catalog)]
        elif query.text and wildcard.is_wildcard(query.text):
            pieces = wildcard.parts(query.text)
            return [a for a in rows if pieces and wildcard.in_order(a.name, pieces)][:50]
        elif query.text:
            t = query.text.lower()
            found = [a for a in rows if t in a.name.lower() or t in (a.catalog or "").lower()]
        else:
            found = []
        return found[:20]

    async def article_by_catalog(self, katalog: str) -> Article | None:
        return next((a for a in self.data.articles if a.catalog == katalog), None)

    async def create_article(self, article: ArticleCreateIn) -> ArticleCreated:
        """D32: catalog checked first, then the card is added (unit ks as Money does); a repeated SMID is returned."""
        for existing_id, smid in self.article_smids.items():
            if smid == article.smid:
                found = next(a for a in self.data.articles if a.id == existing_id)
                return ArticleCreated(
                    id=found.id,
                    katalog=found.catalog or "",
                    nazev=found.name,
                    parent_id=found.parent_id,
                    unit=found.unit,
                    reconciled=True,
                )
        taken = await self.article_by_catalog(article.katalog)
        if taken is not None:
            raise CatalogExists(article.katalog, taken.name)
        new = Article(
            id=uuid.uuid4(),
            code=None,
            catalog=article.katalog,
            name=article.nazev,
            ean=None,
            unit="ks",
            parent_id=article.parent_id,
        )
        self.data.articles.append(new)
        self.article_smids[new.id] = article.smid
        return ArticleCreated(
            id=new.id, katalog=article.katalog, nazev=article.nazev, parent_id=article.parent_id, unit="ks"
        )

    async def article_variants(self, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Article]]:
        out: dict[uuid.UUID, list[Article]] = {p: [] for p in parent_ids}
        for a in self.data.articles:
            if a.parent_id in out:
                out[a.parent_id].append(a)
        return out

    async def article(self, article_id: uuid.UUID) -> Article | None:
        return next((a for a in self.data.articles if a.id == article_id), None)

    async def all_supplier_codes(self, since: datetime | None, start: int, count: int) -> SupplierCodePage:
        rows = self.data.supplier_codes  # the mock has no change dates: a delta returns everything (idempotent)
        page = rows[start : start + count]
        return SupplierCodePage(items=page, next_from=start + count if start + count < len(rows) else None)

    async def lookup_supplier_code(self, supplier_id: uuid.UUID, code: str) -> list[SupplierCode]:
        return [c for c in self.data.supplier_codes if c.supplier_id == supplier_id and c.code == code]

    async def supplier_codes(self, supplier_id: uuid.UUID, start: int, count: int) -> SupplierCodePage:
        rows = [c for c in self.data.supplier_codes if c.supplier_id == supplier_id]
        page = rows[start : start + count]
        return SupplierCodePage(items=page, next_from=start + count if start + count < len(rows) else None)

    # ----- Phase 4c (#247, D33): received delivery note as a koncept -----

    def _note(self, note_id: uuid.UUID) -> dict[str, object] | None:
        return next((n for n in self.data.received_notes if n["ID"] == str(note_id)), None)

    async def create_delivery_note(self, note: DeliveryNoteIn) -> DeliveryNoteCreated:
        """Same order as the API backend: own SMID → reconciled; same supplier + Odkaz → `DuplicateNote`; else the
        koncept is stored (number from the branch series, address from the company card as Money would)."""
        from app.api_backend import note_created_from

        smid = f"SMID:{note.smid}"
        for raw in self.data.received_notes:
            if smid in str(raw.get("Poznamka") or ""):
                return note_created_from(raw, reconciled=True)
        for raw in self.data.received_notes:
            if raw.get("Firma_ID") == str(note.Firma_ID) and raw.get("Odkaz") == note.Odkaz:
                raise DuplicateNote(str(raw.get("CisloDokladu")))
        data = note.money_input()
        company = await self.company(note.Firma_ID)
        n = len(self.data.received_notes) + 1
        items = []
        for i, item in enumerate(data["Polozky"], start=1):
            items.append({**item, "ID": str(uuid.uuid4()), "CisloPolozky": i})
        base = sum((Decimal(it["Mnozstvi"]) * Decimal(it["JednCena"]) for it in data["Polozky"]), Decimal("0"))
        raw = {
            **data,
            "ID": str(uuid.uuid4()),
            "Deleted": False,
            "CisloDokladu": f"DLP{n:04d}/2026",
            "AdresaNazev": company.name if company else None,
            "Firma": {"Nazev": company.name if company else None},
            "Create_Date": datetime.now(UTC).isoformat(),
            "SumaZaklad": base.quantize(Decimal("0.01")),
            "CelkovaCastka": base.quantize(Decimal("0.01")),
            "Polozky": items,
        }
        self.data.received_notes.append(raw)
        return note_created_from(raw, reconciled=False)

    async def received_notes(self, centre_id: uuid.UUID, count: int) -> list[ReceivedNoteRow]:
        from app.api_backend import note_row_from

        rows = [r for r in self.data.received_notes if r.get("Stredisko_ID") == str(centre_id)]
        rows.sort(key=lambda r: (str(r.get("Create_Date") or ""), str(r.get("CisloDokladu") or "")), reverse=True)
        return [note_row_from(r) for r in rows[:count]]

    async def delivery_note_template(self, note_id: uuid.UUID) -> DeliveryNoteTemplate | None:
        from app.api_backend import template_from

        raw = self._note(note_id)
        return template_from(raw) if raw else None
