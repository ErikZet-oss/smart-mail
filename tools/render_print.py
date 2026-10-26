#!/usr/bin/env python3
"""
render_print.py — renders a Money-style print document (DOCUMENTS_SPEC §4–§5) from a JSON fixture to PDF.

    python tools/render_print.py fixtures/documents/offer_sample.json out/offer_sample.pdf

Reference implementation of app/documents/print_render.py: the app uses the same functions (format_*, compute_totals,
build_context) and the same template (templates/print/document.html.j2 + money_print.css). Golden test: the PDF of
every fixture is rasterised (150 dpi) and compared with fixtures/documents/<name>.png (pixel diff < 0.5 %).

Rules (never change without updating DOCUMENTS_SPEC §4.5):
  * Decimal only. Quantity 4 dp, unit price 4 dp, money 2 dp, ROUND_HALF_UP (as Money).
  * line base = round(qty * unit_price, 2); line gross = round(base * (1 + rate/100), 2) (informative column)
  * VAT recap per rate: base = sum of line bases, vat = round(base * rate/100, 2), total = base + vat
  * "Celková čiastka" = sum of recap totals. Text lines (is_text) have no numbers.
  * SK number format: thousands separated by a space, decimal comma ("2 000 000,0000", "567,52 €").
Requirements: weasyprint, jinja2, python-barcode (Code128 SVG).
"""

from __future__ import annotations

import io
import json
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import barcode
from barcode.writer import SVGWriter
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from weasyprint import HTML

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates" / "print"
Q2, Q4 = Decimal("0.01"), Decimal("0.0001")
VAT_LABELS = {
    Decimal("0"): "nulová 0%",
    Decimal("5"): "znížená 5%",
    Decimal("19"): "znížená 19%",
    Decimal("23"): "základná 23%",
}


def dec(v) -> Decimal:
    if isinstance(v, float):
        raise TypeError("floats are not allowed for money or quantities")
    return Decimal(str(v))


def fmt(v: Decimal, places: int) -> str:
    q = v.quantize(Q4 if places == 4 else Q2, rounding=ROUND_HALF_UP)
    sign = "-" if q < 0 else ""
    whole, _, frac = f"{abs(q):.{places}f}".partition(".")
    groups = []
    while whole:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    return f"{sign}{' '.join(groups)},{frac}"


def compute_totals(items: list[dict]) -> dict:
    lines, recap = [], {}
    for it in items:
        if it.get("is_text"):
            lines.append({"is_text": True, "name": it["name"]})
            continue
        qty, price, rate = dec(it["qty"]), dec(it["unit_price"]), dec(it["vat_rate"])
        base = (qty * price).quantize(Q2, rounding=ROUND_HALF_UP)
        gross = (base * (1 + rate / 100)).quantize(Q2, rounding=ROUND_HALF_UP)
        recap.setdefault(rate, Decimal("0"))
        recap[rate] += base
        lines.append(
            {
                "is_text": False,
                "name": it["name"],
                "catalog": it.get("catalog", ""),
                "qty": fmt(qty, 4),
                "unit": it["unit"],
                "unit_price": fmt(price, 4),
                "vat_label": f"{rate.normalize():f}%",
                "base": fmt(base, 2),
                "gross": fmt(gross, 2) + " €",
                "_base": base,
                "_gross": gross,
            }
        )
    rows, sb, sv = [], Decimal("0"), Decimal("0")
    for rate in sorted(recap):
        b = recap[rate]
        v = (b * rate / 100).quantize(Q2, rounding=ROUND_HALF_UP)
        rows.append(
            {
                "label": VAT_LABELS.get(rate, f"{rate.normalize():f}%"),
                "base": fmt(b, 2),
                "vat": fmt(v, 2),
                "total": fmt(b + v, 2),
            }
        )
        sb, sv = sb + b, sv + v
    return {
        "lines": lines,
        "vat_rows": rows,
        "vat_sum": {"base": fmt(sb, 2), "vat": fmt(sv, 2), "total": fmt(sb + sv, 2)},
        "total": fmt(sb + sv, 2) + " €",
        "_total": sb + sv,
    }


def barcode_svg(value: str) -> str:
    buf = io.BytesIO()
    barcode.get("code128", value, writer=SVGWriter()).write(
        buf, options={"write_text": False, "module_height": 6.4, "quiet_zone": 0, "module_width": 0.25}
    )
    svg = buf.getvalue().decode("utf-8")
    svg = svg[svg.index("<svg") :]
    return svg.replace("<svg ", '<svg preserveAspectRatio="none" ', 1)


def build_context(data: dict) -> dict:
    doc = dict(data["doc"])
    doc.update(compute_totals(data["doc"]["items"]))
    return {
        "doc": doc,
        "company": data["company"],
        "partner": data["partner"],
        "footer": data["footer"],
        "barcode_svg": barcode_svg(doc["number"]),
        "css_href": (TEMPLATES / "money_print.css").as_uri(),
        "logo_href": (TEMPLATES / "assets" / "logo.png").as_uri(),
    }


def render(data: dict, out_pdf: Path) -> None:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True, undefined=StrictUndefined)
    html = env.get_template("document.html.j2").render(**build_context(data))
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(TEMPLATES)).write_pdf(out_pdf)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    render(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")), Path(sys.argv[2]))
    print("written", sys.argv[2])
