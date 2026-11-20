"""Bridge response models — shared by the mock and the real Money backend (one contract, CLAUDE.md §0.1).

Field names are English; the Money source field is in each comment. Money values are `Decimal` (JSON: strings).
Enum-like Money integers (`Stav`, `TypDokladu`, `Vyrizeno`) are passed through raw: their meaning is [PROBE] and is
never guessed here.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

InvoiceKind = Literal["invoice", "proforma"]
# #222: documents whose PDF comes from Money's generic print endpoint `/pdfreport` (whitelist, extendable)
DocumentKind = Literal["issued_delivery_note"]
DeliveryMatchedBy = Literal["number", "order", "company", "none"]
CodebookName = Literal["warehouses", "centres", "numerical-series", "currencies", "activity-types"]
MatchedBy = Literal["number", "variable_symbol", "reference", "company_dates", "number_digits", "order", "none"]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Connection(_Model):
    kind: str | None  # TypSpojeni.Kod
    value: str  # SpojeniCislo


class Company(_Model):
    id: uuid.UUID
    code: str | None  # Kod
    name: str  # Nazev
    ico: str | None
    dic: str | None
    icdph: str | None
    email: str | None
    discount_pct: Decimal | None  # HodnotaSlevy
    own_discount: bool | None  # VlastniSleva
    due_days: int | None  # SplatnostPohledavek
    connections: list[Connection]  # SeznamSpojeni


class Person(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None  # REST parent_ID — that it is the company is [PROBE]
    first_name: str | None
    last_name: str | None
    name: str | None
    function: str | None
    email: str | None
    phone: str | None


class IssuedInvoice(_Model):
    id: uuid.UUID
    kind: InvoiceKind
    number: str  # CisloDokladu
    variable_symbol: str | None
    company_id: uuid.UUID | None  # Firma_ID
    issued_on: date | None
    due_on: date | None
    paid_on: date | None  # DatumUhrady
    total: Decimal  # CelkovaCastka
    remaining: Decimal  # UhradyZbyva
    currency_id: uuid.UUID | None
    reference: str | None  # Odkaz
    doc_type: int | None  # TypDokladu, raw
    centre_id: uuid.UUID | None = None  # Stredisko_ID — selects the branch print report (#174)
    description: str | None = None  # Nazev = card „Popis“; holds the e-shop order number (#210)
    note: str | None = None  # Poznamka = card „Poznámka“; also holds the customer's order number (#217)


class Order(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    reference: str | None
    state: int | None  # Stav, raw
    done: int | None  # Vyrizeno, raw
    total: Decimal


class Delivery(_Model):
    id: uuid.UUID
    number: str
    company_id: uuid.UUID | None
    issued_on: date | None
    moved_on: date | None  # DatumSkladovehoPohybu
    reference: str | None
    state: int | None  # Stav, raw
    transport: str | None  # ZpusobDopravy.Nazev
    total: Decimal
    centre_id: uuid.UUID | None = None  # Stredisko_ID — selects the branch print report (#222)
    description: str | None = None  # Nazev = „Popis“; usually holds the customer's order number (#222)
    note: str | None = None  # Poznamka = „Poznámka“; also the customer's order number (#222)


class Activity(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None
    person_id: uuid.UUID | None
    type_id: uuid.UUID | None
    description: str | None  # popis
    started_at: datetime | None
    done: bool | None


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


class OverduePage(_Model):
    """Issued invoices with a balance and due before a date, all customers (W8b Upomienky)."""

    items: list[IssuedInvoice]
    next_from: int | None


class InvoiceSearch(_Model):
    matched_by: MatchedBy
    items: list[IssuedInvoice]


class DeliverySearch(_Model):
    """#222 issued delivery notes: by number, by the customer's order in Popis/Poznámka, or the company's latest."""

    matched_by: DeliveryMatchedBy
    items: list[Delivery]


class ActivityIn(_Model):
    """Phase 3f: CRM activity after a person sent an e-mail to a Money company (REST `Activity`). Only the subject and
    document numbers — never a mail body. `smid` = `SMID:<draft_id>` makes the write idempotent."""

    company_id: uuid.UUID
    type_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    smid: str = Field(pattern=r"^SMID:[0-9a-f-]{36}$")


CATALOG_RE = r"^[^~#|()]{1,50}$"  # used in a filter (`Katalog~eq~…`), so never a filter character
SMID_RE = r"^[A-Za-z0-9-]{8,64}$"


class ArticleCreateIn(_Model):
    """D32 (#239) `CreateArticle` — only these values; Money fills unit, VAT and kind, the card lands in the unnamed
    root group without a category. Never a group, category, unit, VAT or parameter."""

    katalog: str = Field(pattern=CATALOG_RE)
    nazev: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None  # NadrazenyArtikl_ID — a variant of this main card
    smid: str = Field(pattern=SMID_RE)  # written to Poznamka as `SMID:<smid> · Smart Mail`


class ArticleCreated(_Model):
    id: uuid.UUID
    katalog: str
    nazev: str
    parent_id: uuid.UUID | None = None
    unit: str | None = None  # read back: HlavniJednotka.Kod filled by Money
    reconciled: bool = False  # True = the create answered with an error, the card was then found by its catalog + SMID


class CatalogArticle(_Model):
    katalog: str
    nazev: str


class CatalogFree(_Model):
    free: bool
    article: CatalogArticle | None = None


class ActivityOut(_Model):
    id: uuid.UUID
    created: bool  # False = an activity with this SMID already existed (idempotent repeat)


class Health(_Model):
    status: str
    version: str
    backend: str
    agenda: str
    writes_enabled: bool


# ----- Phase 4b: articles and supplier codes (read-only, MONEY_API §5.5.3–§5.5.4) -----


class ArticleUnit(_Model):
    code: str | None  # e.g. ks, bal
    qty: Decimal | None  # how many main units (`Mnozstvi`), e.g. bal = 200 ks
    decimals: int | None = None  # `DesetinnaMista`


class Article(_Model):
    id: uuid.UUID
    code: str | None  # Kod
    catalog: str | None  # Katalog
    name: str
    ean: str | None  # CarovyKod
    unit: str | None  # main unit (HlavniJednotka.Kod)
    units: list[ArticleUnit] = []
    inactive: bool = False
    parent_id: uuid.UUID | None = None  # NadrazenyArtikl_ID — a variant points to its main card (#233)


class SupplierCode(_Model):
    """`ArticleSuppliers` row: the supplier's code for one of our articles."""

    id: uuid.UUID | None = None  # `ArticleSuppliers.ID` — the key of the app's read cache (#228)
    article_id: uuid.UUID
    supplier_id: uuid.UUID
    code: str
    name: str | None
    last_price: Decimal | None
    unit: str | None  # unit the supplier sells in (`Jednotka.Kod`)
    article_unit: str | None  # our unit that corresponds to it (`ArtiklJednotka.Kod`)
    article_unit_qty: Decimal | None  # `ArtiklJednotka.Mnozstvi` (main units per supplier unit)


class SupplierCodePage(_Model):
    items: list[SupplierCode]
    next_from: int | None
