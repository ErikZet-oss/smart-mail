"""Phase 4c (#247, D33) — the received delivery note written to Money as a KONCEPT.

- `koncept_checks`: DL-B1 / DL-B5 / DL-B6 (branch values + template) — shown in W6h and re-run at approval.
- `build_payload`: DOCUMENTS_SPEC §2 + MONEY_API 5.5.7 — `Faze` 0, `Schvaleno` false, Popis „Smartmail · …“,
  header IDs and line values copied from the branch template (never guessed), branch centre on header and items,
  line warehouse, branch series. Decimals end-to-end (sent as strings), fees as side costs of the stock lines (D34),
  no negative quantities (D15).
- `compare`: read-back vs the payload (lines, quantities, prices, article, warehouse, totals) — a mismatch only shows
  the red banner „Skontrolujte koncept v Money“; Smart Mail never edits or deletes the note (D33).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from app.ai.guards import check
from app.auth.models import Branch
from app.money.schemas import DeliveryNoteCreated
from app.purchasing.models import DocumentLine, SupplierDocument

TZ = ZoneInfo("Europe/Bratislava")  # D13: the moment of the write, local time
PREFIX = "Smartmail · "  # D33: Popis of every note written by Smart Mail
POPIS_MAX = 100
Q2 = Decimal("0.01")
Q4 = Decimal("0.0001")
TOLERANCE = Decimal("0.01")
SERIES_KEY = "received_delivery_note"  # branches.series_overrides (SETTINGS 11e „Číselné rady pobočky“)
# DOCUMENTS_SPEC §2.6 / D33: values the API has no codebook for — they must come from the branch template
REQUIRED_HEADER = ("DruhPohybu_ID", "DruhSkladovehoPohybu_ID", "Predkontace_ID", "Group_ID")
REQUIRED_LINE = ("TypObsahu", "TypCeny")
HEADER_COPY = (
    "DruhPohybu_ID",
    "DruhSkladovehoPohybu_ID",
    "Predkontace_ID",
    "RegistraceDPH_ID",
    "DruhDokladu_ID",
    "Group_ID",
    "Mena_ID",
)


@dataclass(frozen=True, slots=True)
class BranchValues:
    centre: str | None
    warehouse: str | None
    series: str | None  # branch override, else the template's CiselnaRada_ID


def template_of(branch: Branch | None) -> dict[str, Any]:
    return dict((branch.dl_template_values or {}) if branch else {})


def branch_values(branch: Branch | None, invalid: set[str]) -> BranchValues:
    """`invalid` = branch fields whose IDs are not in the current Money agenda (#212) — they count as not set."""
    if branch is None:
        return BranchValues(None, None, None)
    tpl = template_of(branch)
    series = (branch.series_overrides or {}).get(SERIES_KEY) or (tpl.get("header") or {}).get("CiselnaRada_ID")
    return BranchValues(
        centre=None if "money_centre_id" in invalid else branch.money_centre_id,
        warehouse=None if "money_warehouse_id" in invalid else branch.money_warehouse_id,
        series=str(series) if series else None,
    )


def missing_template_values(tpl: dict[str, Any]) -> list[str]:
    header, line = tpl.get("header") or {}, tpl.get("line") or {}
    return [k for k in REQUIRED_HEADER if not header.get(k)] + [k for k in REQUIRED_LINE if line.get(k) is None]


def _rate(value: Decimal | str | None) -> str | None:
    return None if value is None else format(Decimal(str(value)).normalize(), "f")


def koncept_checks(
    doc: SupplierDocument, lines: list[DocumentLine], branch: Branch | None, values: BranchValues
) -> list[dict[str, Any]]:
    """DL-B1 (branch centre / warehouse / series), DL-B5 (every stock line has a warehouse), DL-B6 (template with
    every value the write needs, the VAT rate of every stock line, a text-line type for non-stock lines)."""
    out: list[dict[str, Any]] = []
    if doc.supplier_money_id is None:
        out.append(check("DL-B2", "blocking", reason="not_in_money", ico=doc.supplier_ico))
    if not (doc.delivery_note_number or doc.doc_number):
        out.append(check("DL-B3", "blocking", reason="no_number"))  # `Odkaz` is required for the duplicate check
    missing = [
        k for k, v in (("centre", values.centre), ("warehouse", values.warehouse), ("series", values.series)) if not v
    ]
    if branch is None or missing:
        out.append(check("DL-B1", "blocking", missing=missing if branch else ["branch"]))
    goods = [ln for ln in lines if not ln.is_fee]
    stock = [ln for ln in goods if ln.line_status == "matched"]
    no_wh = [ln.line_no for ln in stock if ln.warehouse_id is None and not values.warehouse]
    for n in no_wh:
        out.append(check("DL-B5", "blocking", n=n))
    tpl = template_of(branch)
    if not tpl or missing_template_values(tpl):
        out.append(check("DL-B6", "blocking", missing=missing_template_values(tpl) if tpl else ["template"]))
        return out
    template_rate = _rate((tpl.get("line") or {}).get("DphSazba"))
    rates = sorted({r for ln in stock if (r := _rate(ln.vat_rate)) is not None and r != template_rate})
    if rates:  # SazbaDPH_ID is copied from the template line — another rate would need an ID we do not have
        out.append(check("DL-B6", "blocking", reason="vat_rate", rates=rates))
    if any(ln.line_status == "non_stock" for ln in goods) and not tpl.get("text_line"):
        out.append(check("DL-B6", "blocking", reason="text_line"))
    return out


def mark(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Tag the checks computed here, so `refresh_checks` can replace them without touching the extraction checks."""
    return [{**c, "params": {**c["params"], "koncept": True}} for c in checks]


def _dec_str(value: Decimal) -> str:
    return format(value.normalize() if value == value.to_integral() else value, "f")


def popis(lines: list[DocumentLine]) -> str:
    """Money default Popis = name of item 1 (DOCUMENTS_SPEC §2.2) — here always with the „Smartmail · “ prefix."""
    first = next((ln for ln in lines if not ln.is_fee), None)
    name = ((first.raw or {}).get("_article") or {}).get("name") if first else None
    text = PREFIX + str(name or (first.name if first else "") or "dodací list")
    return text[:POPIS_MAX]


@dataclass(frozen=True, slots=True)
class Expected:
    """One line as written, for the read-back comparison."""

    order: int
    qty: Decimal
    unit_price: Decimal
    article_id: str | None
    warehouse_id: str | None
    total: Decimal | None = None  # the invoice line total written as `CelkovaCena` (Money derives the unit price)


def fee_total(lines: list[DocumentLine]) -> Decimal:
    """D34: doprava, balné, rozbalné … of the supplier document (line total, else qty × price)."""
    out = Decimal("0")
    for ln in lines:
        if ln.is_fee:
            amount = ln.line_total
            if amount is None and ln.qty is not None and ln.unit_price is not None:
                amount = (ln.qty * ln.unit_price).quantize(Q2, ROUND_HALF_UP)
            out += amount or Decimal("0")
    return out


def side_costs(lines: list[DocumentLine]) -> Decimal:
    """D34: the fees written as side costs — only when there is a stock line to carry them."""
    has_stock = any(not ln.is_fee and ln.line_status != "non_stock" for ln in lines)
    return fee_total(lines) if has_stock else Decimal("0")


def split_evenly(total: Decimal, count: int) -> list[Decimal]:
    """D34 „rovnomerne podľa počtu položiek“ in cents that add up exactly: 2.50 / 3 → 0.83, 0.83, 0.84."""
    if count <= 0 or total <= 0:
        return [Decimal("0")] * max(count, 0)
    share = (total / count).quantize(Q2, ROUND_DOWN)
    extra = int((total - share * count) / Q2)  # remaining cents go to the last lines
    return [share + (Q2 if i >= count - extra else Decimal("0")) for i in range(count)]


def build_payload(
    doc: SupplierDocument,
    lines: list[DocumentLine],
    branch: Branch,
    values: BranchValues,
    *,
    now: datetime,
    issue_on_approval: bool,
    with_address: bool,
) -> tuple[dict[str, Any], list[Expected]]:
    """The bridge body (`DeliveryNoteIn`). Call only when `koncept_checks` and the line checks are green."""
    tpl = template_of(branch)
    header, tline = tpl.get("header") or {}, tpl.get("line") or {}
    local = now.astimezone(TZ)
    today = local.date()
    centre = str(values.centre)
    items: list[dict[str, Any]] = []
    expected: list[Expected] = []
    order = 0
    # D34: the fees are side costs of the stock lines, evenly by their number (Money „Náklady“ default)
    stock_lines = [ln for ln in lines if not ln.is_fee and ln.line_status != "non_stock"]
    fees = side_costs(lines)
    shares = dict(zip((ln.line_no for ln in stock_lines), split_evenly(fees, len(stock_lines)), strict=True))
    for ln in lines:
        if ln.is_fee:
            continue  # D34: a fee is not a line — it is distributed into the stock lines below
        order += 1
        qty = ln.qty if ln.qty is not None else Decimal("0")
        price = ln.unit_price if ln.unit_price is not None else Decimal("0")
        if ln.line_status == "non_stock":
            item: dict[str, Any] = {
                "Poradi": order,
                "Nazev": (ln.name or "Položka")[:255],
                "Mnozstvi": _dec_str(qty),
                "Jednotka": ln.unit,
                "JednCena": _dec_str(price),
                "TypCeny": int(tline["TypCeny"]),
                "TypObsahu": int(tpl["text_line"]["TypObsahu"]),
                "Stredisko_ID": centre,
            }
            expected.append(Expected(order, qty, price.quantize(Q4, ROUND_HALF_UP), None, None))
        else:
            factor = ln.unit_factor or Decimal("1")
            qty_our = qty * factor
            price_our = (price / factor).quantize(Q4, ROUND_HALF_UP)
            # pilot 2026-11-24 (Erik, PROD probe): quantity + the invoice line total → Money keeps the total to the
            # cent and derives the unit price (4 dp, half up); a rounded unit price gave a few cents of difference
            total = ln.line_total if ln.line_total is not None and qty_our > 0 else None
            if total is not None:
                price_our = (total / qty_our).quantize(Q4, ROUND_HALF_UP)
            article = (ln.raw or {}).get("_article") or {}
            warehouse = str(ln.warehouse_id) if ln.warehouse_id else str(values.warehouse)
            content: dict[str, Any] = {
                "Artikl_ID": str(ln.article_id),
                "Sklad_ID": warehouse,
                "Mnozstvi": _dec_str(qty_our),
                "PartnerskyKod": (ln.supplier_code or None),
                "PartnerskyNazev": (ln.name or None) and ln.name[:255],
            }
            if tline.get("VazbaTypVazby") is not None:
                content["VazbaTypVazby"] = int(tline["VazbaTypVazby"])
            # pilot 2026-11-24: „Počet nadradenej položky“ 0 → Money refuses to save an edited line; template value
            for key in ("VazbaPocetNadrizene", "VazbaPocetPodrizene"):
                if tline.get(key) is not None and Decimal(str(tline[key])) > 0:
                    content[key] = _dec_str(Decimal(str(tline[key])))
            item = {
                "Poradi": order,
                "Nazev": str(article.get("name") or ln.name)[:255],
                "Katalog": article.get("catalog"),
                "Mnozstvi": _dec_str(qty_our),
                "Jednotka": article.get("unit"),
                **({"CelkovaCena": _dec_str(total)} if total is not None else {"JednCena": _dec_str(price_our)}),
                "TypCeny": int(tline["TypCeny"]),
                "TypObsahu": int(tline["TypObsahu"]),
                "Stredisko_ID": centre,
                "ObsahPolozky": {k: v for k, v in content.items() if v is not None},
            }
            for key in ("SazbaDPH_ID", "DruhPolozky_ID"):
                if tline.get(key):
                    item[key] = str(tline[key])
            if tline.get("DruhSazbyDPH") is not None:
                item["DruhSazbyDPH"] = int(tline["DruhSazbyDPH"])
            share = shares.get(ln.line_no, Decimal("0"))
            if share > 0 and qty_our > 0:  # D34, PROD probe 302600973: the per-unit values only when sent
                value = total if total is not None else (qty_our * price_our).quantize(Q2, ROUND_HALF_UP)
                item["CelkoveVedlejsiNaklady"] = _dec_str(share)
                item["JednotkoveVedlejsiNaklady"] = _dec_str((share / qty_our).quantize(Q4, ROUND_HALF_UP))
                item["JednotkovaPorizovaciCena"] = _dec_str(((value + share) / qty_our).quantize(Q4, ROUND_HALF_UP))
            expected.append(Expected(order, qty_our, price_our, str(ln.article_id), warehouse, total))
        items.append({k: v for k, v in item.items() if v is not None})
    issued: date = today if issue_on_approval or doc.doc_date is None else doc.doc_date
    if doc.kind == "invoice":
        odkaz, pairing = (doc.delivery_note_number or doc.doc_number), doc.doc_number
    else:
        odkaz, pairing = doc.doc_number, None
    body: dict[str, Any] = {
        "smid": doc.idempotency_key,
        "with_address": with_address,
        "Firma_ID": str(doc.supplier_money_id),
        "CiselnaRada_ID": str(values.series),
        "Stredisko_ID": centre,
        **{k: str(header[k]) for k in HEADER_COPY if header.get(k)},
        "Odkaz": str(odkaz or "")[:50],
        "ParovaciSymbol": pairing[:50] if pairing else None,
        "Nazev": popis(lines),
        "Poznamka": f"Smart Mail · doklad dodávateľa {doc.doc_number or doc.filename}"[:1000],
        "DatumVystaveni": issued.isoformat(),
        "DatumUcetnihoPripadu": today.isoformat(),
        "DatumSkladovehoPohybu": today.isoformat(),
        "CasSkladovehoPohybu": local.replace(tzinfo=None, microsecond=0).isoformat(),
        "Faze": 0,
        "Schvaleno": False,
        "Polozky": items,
        "DodatecnePorizovaciNaklady": _dec_str(fees) if fees > 0 else None,  # D34
    }
    assert all(i["Stredisko_ID"] == body["Stredisko_ID"] for i in items)  # DL-B9 (internal, never fires)
    return {k: v for k, v in body.items() if v is not None}, expected


def body_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode()  # byte-identical to BridgeClient._post


def payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(body_bytes(payload)).hexdigest()


def compare(
    expected: list[Expected], back: DeliveryNoteCreated, side_costs: Decimal = Decimal("0")
) -> list[dict[str, Any]]:
    """Read-back vs what was sent. Empty list = the koncept in Money is what the person approved."""
    out: list[dict[str, Any]] = []
    if back.faze != 0 or back.schvaleno is not False:
        out.append({"field": "koncept", "expected": "Faze 0, Schvaleno false", "got": f"{back.faze}, {back.schvaleno}"})
    if len(back.lines) != len(expected):
        out.append({"field": "lines", "expected": str(len(expected)), "got": str(len(back.lines))})
    for exp, got in zip(expected, back.lines, strict=False):
        if got.qty != exp.qty:
            out.append({"line": exp.order, "field": "qty", "expected": str(exp.qty), "got": str(got.qty)})
        if got.unit_price.quantize(Q4, ROUND_HALF_UP) != exp.unit_price:
            out.append(
                {"line": exp.order, "field": "price", "expected": str(exp.unit_price), "got": str(got.unit_price)}
            )
        if exp.article_id and str(got.article_id) != exp.article_id:
            out.append({"line": exp.order, "field": "article"})
        if exp.warehouse_id and str(got.warehouse_id).lower() != exp.warehouse_id.lower():
            out.append({"line": exp.order, "field": "warehouse"})
    total = sum(
        (e.total if e.total is not None else (e.qty * e.unit_price).quantize(Q2, ROUND_HALF_UP) for e in expected),
        Decimal("0"),
    )
    if abs(side_costs - back.side_costs) > TOLERANCE:  # D34
        out.append({"field": "side_costs", "expected": str(side_costs), "got": str(back.side_costs)})
    if abs(total - back.total_base) > TOLERANCE:
        out.append({"field": "total", "expected": str(total), "got": str(back.total_base)})
    return out


def new_smid() -> str:
    return uuid.uuid4().hex
