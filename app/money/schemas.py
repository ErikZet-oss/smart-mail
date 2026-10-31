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

CodebookName = Literal["warehouses", "centres", "numerical-series", "currencies"]
CODEBOOKS: tuple[CodebookName, ...] = ("warehouses", "centres", "numerical-series", "currencies")


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


class InvoiceSearch(_Model):
    matched_by: Literal["number", "variable_symbol", "reference", "company_dates", "number_digits", "none"]
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


class Activity(_Model):
    id: uuid.UUID
    company_id: uuid.UUID | None
    person_id: uuid.UUID | None
    type_id: uuid.UUID | None
    description: str | None
    started_at: datetime | None
    done: bool | None


class Health(_Model):
    status: str
    version: str
    backend: str
    agenda: str
    writes_enabled: bool
