"""Bridge response models as the main app reads them — the same contract as `bridge/app/models.py`.

`fixtures/money/bridge_contract.json` is produced from the bridge mock; the bridge suite fails when its output drifts
from the fixture and the app suite parses the fixture with these models (`extra="forbid"`), so both sides stay equal.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

CodebookName = Literal["warehouses", "centres", "numerical-series", "currencies", "activity-types"]
CODEBOOKS: tuple[CodebookName, ...] = ("warehouses", "centres", "numerical-series", "currencies", "activity-types")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Connection(_Model):
    kind: str | None
    value: str


class Company(_Model):
    id: uuid.UUID
    code: str | None
    name: str
    ico: str | None
    dic: str | None
    icdph: str | None
    email: str | None
    discount_pct: Decimal | None
    own_discount: bool | None
    due_days: int | None
    connections: list[Connection]


class Person(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None
    first_name: str | None
    last_name: str | None
    name: str | None
    function: str | None
    email: str | None
    phone: str | None


class CodebookItem(_Model):
    id: uuid.UUID
    code: str | None
    name: str | None


class CompanyPage(_Model):
    items: list[Company]
    next_from: int | None


class PersonPage(_Model):
    items: list[Person]
    next_from: int | None


class CodebookPage(_Model):
    items: list[CodebookItem]
    next_from: int | None


class IssuedInvoice(_Model):
    id: uuid.UUID
    kind: Literal["invoice", "proforma"]
    number: str
    variable_symbol: str | None
    company_id: uuid.UUID | None
    issued_on: date | None
    due_on: date | None
    paid_on: date | None
    total: Decimal
    remaining: Decimal
    currency_id: uuid.UUID | None
    reference: str | None
    doc_type: int | None
    centre_id: uuid.UUID | None = None  # Stredisko_ID (#174)
    description: str | None = None  # Nazev / „Popis“ — the e-shop order number (#210)
    note: str | None = None  # Poznamka / „Poznámka“ — also the customer's order number (#217)


class OverduePage(_Model):
    items: list[IssuedInvoice]
    next_from: int | None


class InvoiceSearch(_Model):
    matched_by: Literal["number", "variable_symbol", "reference", "company_dates", "number_digits", "order", "none"]
    items: list[IssuedInvoice]


class Order(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    reference: str | None
    state: int | None
    done: int | None
    total: Decimal


class Delivery(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    moved_on: date | None
    reference: str | None
    state: int | None
    transport: str | None
    total: Decimal
    centre_id: uuid.UUID | None = None  # Stredisko_ID → the branch print report (#222)
    description: str | None = None  # Nazev / „Popis“ — usually the customer's order number (#222)
    note: str | None = None  # Poznamka / „Poznámka“ (#222)


class DeliverySearch(_Model):
    """#222 issued delivery notes found by number, by the customer's order or the company's latest."""

    matched_by: Literal["number", "order", "company", "none"]
    items: list[Delivery]


class Activity(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None
    person_id: uuid.UUID | None
    type_id: uuid.UUID | None
    description: str | None
    started_at: datetime | None
    done: bool | None


class ActivityOut(_Model):
    id: uuid.UUID
    created: bool


class Health(_Model):
    status: str
    version: str
    backend: str
    agenda: str
    writes_enabled: bool


# ----- Phase 4b: articles and supplier codes (read-only; mirrors bridge/app/models.py) -----


class ArticleUnit(_Model):
    code: str | None
    qty: Decimal | None
    decimals: int | None = None


class Article(_Model):
    id: uuid.UUID
    code: str | None
    catalog: str | None
    name: str
    ean: str | None
    unit: str | None
    units: list[ArticleUnit] = []
    inactive: bool = False
    parent_id: uuid.UUID | None = None  # NadrazenyArtikl_ID: a variant → its main card (#233)


class ArticleCreated(_Model):
    """D32 (#239) the card read back after `CreateArticle` (bridge `ArticleCreated`)."""

    id: uuid.UUID
    katalog: str
    nazev: str
    parent_id: uuid.UUID | None = None
    unit: str | None = None
    reconciled: bool = False


class CatalogArticle(_Model):
    katalog: str
    nazev: str


class CatalogFree(_Model):
    free: bool
    article: CatalogArticle | None = None


class SupplierCode(_Model):
    id: uuid.UUID | None = None  # `ArticleSuppliers.ID` — key of `money_article_suppliers` (#228)
    article_id: uuid.UUID
    supplier_id: uuid.UUID
    code: str
    name: str | None
    last_price: Decimal | None
    unit: str | None
    article_unit: str | None
    article_unit_qty: Decimal | None


class SupplierCodePage(_Model):
    items: list[SupplierCode]
    next_from: int | None


# ----- Phase 4c (#247, D33): received delivery note as a koncept (bridge `DeliveryNoteCreated` …) -----


class DeliveryNoteLineBack(_Model):
    id: uuid.UUID | None
    number: int | None
    order: int | None
    qty: Decimal
    unit_price: Decimal
    content_type: int | None
    article_id: uuid.UUID | None
    warehouse_id: uuid.UUID | None
    centre_id: uuid.UUID | None


class DeliveryNoteCreated(_Model):
    id: uuid.UUID
    number: str | None
    faze: int | None
    schvaleno: bool | None
    group_id: uuid.UUID | None
    centre_id: uuid.UUID | None
    total_base: Decimal
    total: Decimal
    address_empty: bool
    lines: list[DeliveryNoteLineBack]
    reconciled: bool = False


class ReceivedNoteRow(_Model):
    id: uuid.UUID
    number: str | None
    supplier: str | None
    issued_on: date | None
    koncept: bool
    by_smart_mail: bool


class DeliveryNoteTemplate(_Model):
    id: uuid.UUID
    number: str | None
    supplier: str | None
    issued_on: date | None
    centre_id: uuid.UUID | None
    header: dict[str, str]
    line: dict[str, str | int]
    text_line: dict[str, int] | None
