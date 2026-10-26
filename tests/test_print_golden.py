"""Golden print documents (CLAUDE.md §0.1, DOCUMENTS_SPEC §4): render each fixture with the reference renderer,
rasterise at 150 dpi and compare with fixtures/documents/<name>.png — pixel diff must stay below 0.5 %.
Fails loudly when the narrow print font is missing (templates/print/fonts/README.md)."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "documents"
MAX_DIFF = 0.005
GOLDEN = ["offer_sample", "order_confirmation_sample"]

spec = importlib.util.spec_from_file_location("render_print", ROOT / "tools" / "render_print.py")
assert spec and spec.loader
render_print = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_print)


def test_narrow_font_installed() -> None:
    fc_list = shutil.which("fc-list")
    assert fc_list, "fontconfig (fc-list) is required for print rendering"
    fonts = subprocess.run([fc_list], capture_output=True, text=True, check=True).stdout
    assert "Arial Narrow" in fonts or "Liberation Sans Narrow" in fonts, (
        "Install templates/print/fonts/*.ttf (Liberation Sans Narrow) — see templates/print/fonts/README.md"
    )


def _raster(pdf: Path) -> Image.Image:
    """Same rasteriser as the golden PNGs: poppler `pdftoppm -r 150` (package poppler-utils)."""
    exe = shutil.which("pdftoppm")
    assert exe, "pdftoppm (poppler-utils) is required for golden print tests"
    stem = pdf.with_suffix("")
    subprocess.run([exe, "-r", "150", "-png", "-singlefile", "-f", "1", "-l", "1", str(pdf), str(stem)], check=True)
    return Image.open(f"{stem}.png").convert("RGB")


@pytest.mark.golden
@pytest.mark.parametrize("name", GOLDEN)
def test_print_matches_golden(name: str, tmp_path: Path) -> None:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    out = tmp_path / f"{name}.pdf"
    render_print.render(data, out)
    got = _raster(out)
    want = Image.open(FIXTURES / f"{name}.png").convert("RGB")
    assert got.size == want.size, f"page size changed: {got.size} != {want.size}"
    diff = ImageChops.difference(got, want).convert("L").point(lambda v: 255 if v > 48 else 0)
    changed = diff.histogram()[255] / (got.size[0] * got.size[1])
    if changed >= MAX_DIFF:
        got.save(tmp_path / f"{name}.got.png")
    assert changed < MAX_DIFF, f"{name}: {changed:.3%} pixels differ (limit {MAX_DIFF:.1%}), see {tmp_path}"


def test_totals_use_decimal_half_up() -> None:
    from decimal import Decimal

    items = [{"name": "x", "unit": "ks", "qty": "3", "unit_price": "0.0125", "vat_rate": "23"}]
    totals = render_print.compute_totals(items)
    # 3 x 0,0125 = 0,0375 -> 0,04 (ROUND_HALF_UP like Money); VAT 23 % of 0,04 = 0,0092 -> 0,01
    assert totals["lines"][0]["base"] == "0,04"
    assert totals["vat_sum"] == {"base": "0,04", "vat": "0,01", "total": "0,05"}
    assert isinstance(totals["_total"], Decimal)
