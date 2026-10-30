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

from pydantic import BaseModel, ConfigDict

InvoiceKind = Literal["invoice", "proforma"]
CodebookName = Literal["warehouses", "centres", "numerical-series", "currencies"]
MatchedBy = Literal["number", "variable_symbol", "reference", "company_dates", "number_digits", "none"]


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


class InvoiceSearch(_Model):
    matched_by: MatchedBy
    items: list[IssuedInvoice]


class Health(_Model):
    status: str
    version: str
    backend: str
    agenda: str
    writes_enabled: bool
