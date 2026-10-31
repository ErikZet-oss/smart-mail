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
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    InvoiceKind,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    OverduePage,
    PersonPage,
)


class MoneyUnavailable(Exception):
    """Money (or the network to it) did not answer — mail must keep working, callers show „Money nedostupné“."""


class MoneyError(Exception):
    """Money answered with an error (GraphQL `errors`, 4xx/5xx other than auth)."""


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

    async def create_activity(self, activity: ActivityIn) -> ActivityOut: ...

    async def aclose(self) -> None: ...
