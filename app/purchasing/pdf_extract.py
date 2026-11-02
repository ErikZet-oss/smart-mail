"""PDF supplier document → ExtractedDoc: pdfplumber text + tables, then ONE LLM call with a JSON schema (DECISIONS D3).

- Scans without a text layer return `None` (status `unreadable`); OCR comes later (CLAUDE.md §2 ocrmypdf).
- The document text is untrusted data (AI_ASSISTANT guards): wrapped, its wrapper tags neutralised, never logged.
- Numbers come back as printed strings and are parsed here with `parse_decimal` — the model never computes prices;
  a `price_per` of 100/1000 is divided here, in Decimal.
"""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import pdfplumber

from app.ai.provider import LLMProvider, LLMRequest, LLMResponse
from app.ai.reply import render_prompt
from app.purchasing.numbers import parse_decimal
from app.purchasing.schemas import DocKind, ExtractedDoc, ExtractedLine, VatRow
from app.purchasing.xmlparse import is_fee

MAX_PAGES = 30
MAX_CHARS = 60_000
TOOL = "extract_supplier_document"
_WRAPPER = re.compile(r"</?\s*untrusted_document\s*>", re.IGNORECASE)

_STR = {"type": "string"}
TOOL_SCHEMA: dict[str, object] = {
    "name": TOOL,
    "description": "Return the supplier document as structured data.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": ["invoice", "delivery_note", "unknown"]},
            "supplier_name": _STR,
            "supplier_ico": _STR,
            "number": _STR,
            "delivery_note_number": _STR,
            "order_reference": _STR,
            "issued_on": {"type": "string", "description": "YYYY-MM-DD"},
            "currency": _STR,
            "total": _STR,
            "vat_recap": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"rate": _STR, "base": _STR, "vat": _STR},
                    "required": ["rate", "base"],
                },
            },
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "supplier_code": _STR,
                        "ean": _STR,
                        "name": _STR,
                        "qty": _STR,
                        "unit": _STR,
                        "unit_price": _STR,
                        "unit_price_printed": _STR,
                        "price_per": _STR,
                        "vat_rate": _STR,
                        "line_total": _STR,
                        "is_fee": {"type": "boolean"},
                    },
                    "required": ["name"],
                },
            },
            "confidence": {"type": "object", "additionalProperties": {"type": "number"}},
        },
        "required": ["kind", "lines"],
    },
}


def pdf_text(data: bytes) -> str | None:
    """Text layer + tables (rows joined with ` | `). None when the PDF has no text (a scan) or cannot be read."""
    parts: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for n, page in enumerate(pdf.pages[:MAX_PAGES], start=1):
                text = page.extract_text() or ""
                tables = page.extract_tables() or []
                block = [f"--- page {n} ---", text]
                for t in tables:
                    block.append("[table]")
                    block.extend(" | ".join((c or "").replace("\n", " ") for c in row) for row in t if row)
                parts.append("\n".join(block))
    except Exception:  # broken / encrypted PDF: the caller marks the document unreadable
        return None
    text = "\n".join(parts).strip()
    if len(re.sub(r"\W", "", text.replace("--- page", ""))) < 40:
        return None
    return text[:MAX_CHARS]


def _s(v: Any) -> str | None:
    return None if v in (None, "") else str(v).strip() or None


def _date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _line(raw: dict[str, Any]) -> ExtractedLine:
    name = _s(raw.get("name")) or ""
    unit_price = parse_decimal(_s(raw.get("unit_price")))
    printed = parse_decimal(_s(raw.get("unit_price_printed")))
    per = parse_decimal(_s(raw.get("price_per")))
    if printed is not None and per is not None and per > 0:
        unit_price = printed / per  # price per 100 / 1000 pieces → per one piece, exact Decimal
    return ExtractedLine(
        supplier_code=_s(raw.get("supplier_code")),
        ean=_s(raw.get("ean")),
        name=name,
        qty=parse_decimal(_s(raw.get("qty"))),
        unit=_s(raw.get("unit")),
        unit_price=unit_price,
        vat_rate=parse_decimal(_s(raw.get("vat_rate"))),
        line_total=parse_decimal(_s(raw.get("line_total"))),
        is_fee=bool(raw.get("is_fee")) or is_fee(name),
    )


def doc_from_tool(data: dict[str, Any]) -> ExtractedDoc:
    kind = data.get("kind")
    vat: list[VatRow] = []
    for row in data.get("vat_recap") or []:
        rate, base = parse_decimal(_s(row.get("rate"))), parse_decimal(_s(row.get("base")))
        if rate is not None and base is not None:
            vat.append(VatRow(rate=rate, base=base, vat=parse_decimal(_s(row.get("vat")))))
    confidence = {str(k): v for k, v in (data.get("confidence") or {}).items() if isinstance(v, int | float)}
    doc_kind: DocKind = kind if kind in ("invoice", "delivery_note") else "unknown"
    return ExtractedDoc(
        kind=doc_kind,
        method="pdf_llm",
        supplier_name=_s(data.get("supplier_name")),
        supplier_ico=(_s(data.get("supplier_ico")) or "").replace(" ", "") or None,
        number=_s(data.get("number")),
        delivery_note_number=_s(data.get("delivery_note_number")),
        order_reference=_s(data.get("order_reference")),
        issued_on=_date(data.get("issued_on")),
        currency=(_s(data.get("currency")) or "").upper()[:3] or None,
        total=parse_decimal(_s(data.get("total"))),
        vat_recap=vat,
        lines=[_line(r) for r in data.get("lines") or [] if isinstance(r, dict)],
        confidence=confidence,
    )


async def extract_pdf(provider: LLMProvider, model: str, text: str) -> tuple[ExtractedDoc | None, LLMResponse]:
    """One LLM call. Returns (None, response) when the model did not call the tool."""
    response = await provider.complete(
        LLMRequest(
            purpose="extract",
            system="You extract data from business documents into the given tool. Output only the tool call.",
            user=render_prompt("extract_supplier", document=_WRAPPER.sub("[tag]", text)),
            model=model,
            max_tokens=8000,
            tools=(TOOL_SCHEMA,),
            tool_choice={"type": "tool", "name": TOOL},
        )
    )
    if not response.tool_input:
        return None, response
    return doc_from_tool(dict(response.tool_input)), response
