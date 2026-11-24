"""The one interface both backends implement (mock in CI, Money API on the office server). Read-only in Phase 3."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from app.models import (
    Activity,
    ActivityIn,
    ActivityOut,
    Article,
    ArticleCatalogInfo,
    ArticleCreated,
    ArticleCreateIn,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    DeliveryNoteCreated,
    DeliveryNoteIn,
    DeliveryNoteTemplate,
    DeliverySearch,
    DocumentKind,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    OverduePage,
    PersonPage,
    ReceivedNoteRow,
    SupplierCode,
    SupplierCodePage,
)


class MoneyUnavailable(Exception):
    """Money (or the network to it) did not answer — mail must keep working, callers show „Money nedostupné“."""


class MoneyError(Exception):
    """Money answered with an error (GraphQL `errors`, 4xx/5xx other than auth)."""


class CatalogExists(Exception):
    """D32: an article with this catalog number already exists in Money — nothing was created."""

    def __init__(self, katalog: str, nazev: str) -> None:
        super().__init__(katalog)
        self.katalog = katalog
        self.nazev = nazev


class DuplicateNote(Exception):
    """DL-B3 (#247): a received delivery note of the same supplier (`Firma_ID`) + `Odkaz` is already in Money —
    nothing was created."""

    def __init__(self, number: str | None) -> None:
        super().__init__(number or "")
        self.number = number


class WaitingForProbe(Exception):
    """The call needs a detail only `probe_output/report.md` can confirm; never guessed (CLAUDE.md §0, §7)."""

    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


@dataclass(frozen=True)
class InvoiceQuery:
    """MONEY_API §5.1 search cascade inputs; the first non-empty step wins."""

    number: str | None = None
    variable_symbol: str | None = None
    reference: str | None = None
    company_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    order: str | None = None  # #210: e-shop order number in the invoice „Popis“ (`Nazev`)


@dataclass(frozen=True)
class DeliveryQuery:
    """#222: number (exact) → order in „Popis“ / „Poznámka“ → the company's latest; the first non-empty step wins."""

    number: str | None = None
    order: str | None = None
    company_id: uuid.UUID | None = None


@dataclass(frozen=True)
class ArticleQuery:
    """Exact code / catalog / EAN, or a name fragment — one of them (MONEY_API §5.5.3 steps 3, 4, 7)."""

    code: str | None = None  # Kod or Katalog, exact
    ean: str | None = None  # CarovyKod, exact
    text: str | None = None  # Nazev / Katalog contains (manual search)
    limit: int | None = None  # rows of a text search (W6h Katalóg asks for up to 100; default 20 / 50 with `%`)


class MoneyBackend(Protocol):
    async def version(self) -> str: ...

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage: ...

    async def company(self, company_id: uuid.UUID) -> Company | None: ...

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage: ...

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage: ...

    async def search_invoices(self, query: InvoiceQuery) -> InvoiceSearch: ...

    async def receivables(self, company_id: uuid.UUID) -> list[IssuedInvoice]: ...

    async def overdue(self, before: date, start: int, count: int) -> OverduePage: ...

    async def orders(self, company_id: uuid.UUID, since: date) -> list[Order]: ...

    async def deliveries(self, company_id: uuid.UUID, since: date) -> list[Delivery]: ...

    async def activities(self, company_id: uuid.UUID) -> list[Activity]: ...

    async def invoice_pdf(self, kind: InvoiceKind, invoice_id: uuid.UUID, report_id: str) -> bytes | None: ...

    async def search_deliveries(self, query: DeliveryQuery) -> DeliverySearch: ...

    async def document_pdf(
        self, kind: DocumentKind, record_id: uuid.UUID, report_id: str, design_id: str | None
    ) -> bytes | None: ...

    async def create_activity(self, activity: ActivityIn) -> ActivityOut: ...

    async def aclose(self) -> None: ...

    # Phase 4b (read-only): item matching of supplier documents (MONEY_API §5.5.3)
    async def articles(self, query: ArticleQuery) -> list[Article]: ...

    async def article(self, article_id: uuid.UUID) -> Article | None: ...

    async def article_variants(self, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Article]]: ...

    async def catalog_info(self, article_ids: list[uuid.UUID]) -> list[ArticleCatalogInfo]: ...

    async def article_by_catalog(self, katalog: str) -> Article | None: ...

    async def create_article(self, article: ArticleCreateIn) -> ArticleCreated: ...

    async def supplier_codes(self, supplier_id: uuid.UUID, start: int, count: int) -> SupplierCodePage: ...

    async def all_supplier_codes(self, since: datetime | None, start: int, count: int) -> SupplierCodePage: ...

    async def lookup_supplier_code(self, supplier_id: uuid.UUID, code: str) -> list[SupplierCode]: ...

    # ----- Phase 4c (#247, D33): received delivery note as a koncept -----

    async def create_delivery_note(self, note: DeliveryNoteIn) -> DeliveryNoteCreated: ...

    async def received_notes(self, centre_id: uuid.UUID, count: int) -> list[ReceivedNoteRow]: ...

    async def delivery_note_template(self, note_id: uuid.UUID) -> DeliveryNoteTemplate | None: ...
