"""ISDOC (CZ/SK e-invoice) and UBL (Invoice / DespatchAdvice) → ExtractedDoc. Deterministic, no model call (D3).

Namespace-agnostic (local element names), so ISDOC 5.x/6.x and UBL 2.x variants all work. A document with a DOCTYPE
is refused (entity tricks); size is limited by the caller."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from app.purchasing.numbers import parse_decimal
from app.purchasing.schemas import DocKind, ExtractedDoc, ExtractedLine, Method, VatRow

FEE_WORDS = ("doprav", "poštov", "postov", "balné", "balne", "paleta", "palety", "freight", "shipping", "porto")


class NotSupplierXml(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _kids(el: ET.Element | None, name: str) -> list[ET.Element]:
    return [] if el is None else [c for c in el if _local(c.tag) == name]


def _kid(el: ET.Element | None, *path: str) -> ET.Element | None:
    cur = el
    for name in path:
        found = _kids(cur, name)
        if not found:
            return None
        cur = found[0]
    return cur


def _text(el: ET.Element | None, *path: str) -> str | None:
    node = _kid(el, *path) if path else el
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _dec(el: ET.Element | None, *path: str) -> Decimal | None:
    return parse_decimal(_text(el, *path))


def _date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def is_fee(name: str) -> bool:
    low = name.lower()
    return any(w in low for w in FEE_WORDS)


def parse_xml(data: bytes) -> ExtractedDoc:
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise NotSupplierXml("doctype")
    try:
        # S314: DOCTYPE / ENTITY are refused above, so no entity expansion or external entity can occur; stdlib
        # ElementTree never fetches external resources. (defusedxml is not a listed dependency, CLAUDE.md §0.)
        root = ET.fromstring(data)  # noqa: S314
    except ET.ParseError as exc:
        raise NotSupplierXml("not xml") from exc
    name = _local(root.tag)
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    if "isdoc" in ns.lower():
        return _isdoc(root)
    if name in ("Invoice", "CreditNote") and "oasis" in ns.lower():
        return _ubl(root, "invoice", "InvoiceLine", "InvoicedQuantity")
    if name == "DespatchAdvice":
        return _ubl(root, "delivery_note", "DespatchLine", "DeliveredQuantity")
    raise NotSupplierXml(name)


def _party(party: ET.Element | None) -> tuple[str | None, str | None]:
    name = _text(party, "PartyName", "Name") or _text(party, "PartyLegalEntity", "RegistrationName")
    ico = None
    for ident in _kids(party, "PartyIdentification"):
        value = _text(ident, "ID")
        if value and value.replace(" ", "").isdigit():
            ico = value.replace(" ", "")
            break
    ico = ico or _text(party, "PartyLegalEntity", "CompanyID")
    return name, ico


def _vat_rows(subtotals: Iterable[ET.Element]) -> list[VatRow]:
    rows: list[VatRow] = []
    for st in subtotals:
        rate = _dec(st, "TaxCategory", "Percent")
        if rate is None:  # 0 % (reverse charge) is a valid rate — no `or`
            rate = _dec(st, "ClassifiedTaxCategory", "Percent")
        base = _dec(st, "TaxableAmount")
        if rate is not None and base is not None:
            rows.append(VatRow(rate=rate, base=base, vat=_dec(st, "TaxAmount")))
    return rows


def _isdoc(root: ET.Element) -> ExtractedDoc:
    supplier, ico = _party(_kid(root, "AccountingSupplierParty", "Party"))
    lines: list[ExtractedLine] = []
    for ln in _kids(_kid(root, "InvoiceLines"), "InvoiceLine"):
        qty_el = _kid(ln, "InvoicedQuantity")
        name = _text(ln, "Item", "Description") or ""
        lines.append(
            ExtractedLine(
                supplier_code=_text(ln, "Item", "SellersItemIdentification", "ID"),
                ean=_text(ln, "Item", "CatalogueItemIdentification", "ID"),
                name=name,
                qty=_dec(qty_el),
                unit=(qty_el.get("unitCode") if qty_el is not None else None),
                unit_price=_dec(ln, "UnitPrice"),
                vat_rate=_dec(ln, "ClassifiedTaxCategory", "Percent"),
                line_total=_dec(ln, "LineExtensionAmount"),
                is_fee=is_fee(name),
            )
        )
    tax_total = _kid(root, "TaxTotal")
    return ExtractedDoc(
        kind="invoice",
        method="isdoc",
        supplier_name=supplier,
        supplier_ico=ico,
        number=_text(root, "ID"),
        delivery_note_number=_text(root, "DeliveryNoteReferences", "DeliveryNoteReference", "ID"),
        order_reference=_text(root, "OrderReferences", "OrderReference", "SalesOrderID"),
        issued_on=_date(_text(root, "IssueDate")),
        currency=_text(root, "LocalCurrencyCode") or _text(root, "ForeignCurrencyCode"),
        total=_dec(root, "LegalMonetaryTotal", "TaxInclusiveAmount"),
        vat_recap=_vat_rows(_kids(tax_total, "TaxSubTotal")),
        lines=lines,
        confidence={"*": 1.0},
    )


def _ubl(root: ET.Element, kind: DocKind, line_tag: str, qty_tag: str) -> ExtractedDoc:
    supplier_party = _kid(root, "AccountingSupplierParty", "Party")
    if supplier_party is None:  # never `or`: an Element's truth value is its child count
        supplier_party = _kid(root, "DespatchSupplierParty", "Party")
    supplier, ico = _party(supplier_party)
    lines: list[ExtractedLine] = []
    for ln in _kids(root, line_tag):
        qty_el = _kid(ln, qty_tag)
        name = _text(ln, "Item", "Name") or _text(ln, "Item", "Description") or ""
        lines.append(
            ExtractedLine(
                supplier_code=_text(ln, "Item", "SellersItemIdentification", "ID"),
                ean=_text(ln, "Item", "StandardItemIdentification", "ID"),
                name=name,
                qty=_dec(qty_el),
                unit=(qty_el.get("unitCode") if qty_el is not None else None),
                unit_price=_dec(ln, "Price", "PriceAmount"),
                vat_rate=_dec(ln, "Item", "ClassifiedTaxCategory", "Percent"),
                line_total=_dec(ln, "LineExtensionAmount"),
                is_fee=is_fee(name),
            )
        )
    method: Method = "ubl"
    return ExtractedDoc(
        kind=kind,
        method=method,
        supplier_name=supplier,
        supplier_ico=ico,
        number=_text(root, "ID"),
        delivery_note_number=_text(root, "DespatchDocumentReference", "ID"),
        order_reference=_text(root, "OrderReference", "ID"),
        issued_on=_date(_text(root, "IssueDate")),
        currency=_text(root, "DocumentCurrencyCode"),
        total=_dec(root, "LegalMonetaryTotal", "TaxInclusiveAmount"),
        vat_recap=_vat_rows(_kids(_kid(root, "TaxTotal"), "TaxSubTotal")),
        lines=lines,
        confidence={"*": 1.0},
    )
