"""What any extractor (ISDOC, UBL, PDF + LLM) returns. Decimals only; strings in JSON (CLAUDE.md §0.1)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DocKind = Literal["invoice", "delivery_note", "unknown"]
Method = Literal["isdoc", "ubl", "pdf_llm"]


class ExtractedLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    supplier_code: str | None = None
    ean: str | None = None
    name: str = ""
    qty: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None  # excl. VAT, per one unit
    vat_rate: Decimal | None = None
    line_total: Decimal | None = None  # excl. VAT
    is_fee: bool = False  # doprava, balné, palety … (D14: shown, never written)


class VatRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    rate: Decimal
    base: Decimal
    vat: Decimal | None = None


class ExtractedDoc(BaseModel):
    kind: DocKind = "unknown"
    method: Method
    supplier_name: str | None = None
    supplier_ico: str | None = None
    number: str | None = None
    delivery_note_number: str | None = None
    order_reference: str | None = None
    issued_on: date | None = None
    currency: str | None = None
    total: Decimal | None = None  # incl. VAT
    vat_recap: list[VatRow] = Field(default_factory=list)
    lines: list[ExtractedLine] = Field(default_factory=list)
    confidence: dict[str, float] = Field(default_factory=dict)  # field → 0..1 (LLM only; XML = 1)
