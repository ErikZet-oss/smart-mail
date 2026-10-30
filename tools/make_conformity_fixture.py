#!/usr/bin/env python3
"""Regenerate the fictional golden fixture of the Prehlásenie o zhode (#139):

    uv run python tools/make_conformity_fixture.py

Writes fixtures/documents/conformity_sample.{json,pdf,png} and the fictional images conformity_stamp.png /
conformity_signature.png (drawn shapes, no real stamp or signature). Review every change of the PNG.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "documents"
sys.path.insert(0, str(ROOT))

from app.documents.conformity import DeclarationData, Party, Signer, render_html, render_pdf  # noqa: E402


def fictional_stamp() -> bytes:
    image = Image.new("RGBA", (600, 360), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    blue = (36, 72, 168, 230)
    draw.rounded_rectangle((20, 20, 580, 340), radius=40, outline=blue, width=10)
    draw.rounded_rectangle((50, 50, 550, 310), radius=24, outline=blue, width=4)
    for y in (110, 160, 210, 260):
        draw.line((90, y, 510, y), fill=blue, width=8)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def fictional_signature() -> bytes:
    image = Image.new("RGBA", (500, 220), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    ink = (16, 24, 64, 255)
    points = [(20, 160), (70, 60), (110, 170), (150, 70), (200, 150), (260, 90), (320, 140), (400, 80), (480, 120)]
    draw.line(points, fill=ink, width=7, joint="curve")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


SAMPLE = {
    "_comment": "FICTIONAL golden fixture — invented customer, products, branch, signer, stamp and signature; "
    "never real data (#139).",
    "number": "PZ-2026-0001",
    "issued_on": "2026-10-30",
    "customer": "Fiktívna Stavebná s.r.o.\nTestovacia 1, 000 00 Vzorovo",
    "document_ref": "FA 2026/0000",
    "place": "Nitra",
    "branch": {"name": "Pobočka Vzorovo", "address": "Ukážková 12, 000 00 Vzorovo", "phone": "000 / 000 00 00"},
    "signer": {"name": "Ján Vzorový", "function": "Vedúci pobočky"},
    "ico": "",
    "items": [
        {"nazov": "Skrutka samorezná 5,5x67 Zn", "kod": "TEST-0001", "norma": "DIN 7504 K", "poznamka": ""},
        {"nazov": "Matica šesťhranná M8 Zn", "kod": "TEST-0002", "norma": "DIN 934", "poznamka": ""},
        {"nazov": "Podložka 8,4 Zn", "kod": "TEST-0003", "norma": "DIN 125 A", "poznamka": "balenie 100 ks"},
    ],
}


def render_sample(sample: dict[str, object], stamp: bytes, signature: bytes) -> bytes:
    branch = sample["branch"]
    signer = sample["signer"]
    assert isinstance(branch, dict) and isinstance(signer, dict)
    data = DeclarationData(
        number=str(sample["number"]),
        issued_on=date.fromisoformat(str(sample["issued_on"])),
        customer=str(sample["customer"]),
        document_ref=str(sample["document_ref"]),
        place=str(sample["place"]),
        items=list(sample["items"]),  # type: ignore[call-overload]
    )
    html = render_html(
        data,
        branch=Party(branch["name"], branch["address"], branch["phone"]),
        signer=Signer(signer["name"], signer["function"]),
        stamp_png=stamp,
        signature_png=signature,
        ico=str(sample["ico"]),
    )
    return render_pdf(html)


def main() -> int:
    stamp, signature = fictional_stamp(), fictional_signature()
    (FIXTURES / "conformity_stamp.png").write_bytes(stamp)
    (FIXTURES / "conformity_signature.png").write_bytes(signature)
    (FIXTURES / "conformity_sample.json").write_text(json.dumps(SAMPLE, ensure_ascii=False, indent=2) + "\n")
    pdf = FIXTURES / "conformity_sample.pdf"
    pdf.write_bytes(render_sample(SAMPLE, stamp, signature))
    exe = shutil.which("pdftoppm")
    assert exe, "pdftoppm (poppler-utils) is required"
    stem = FIXTURES / "conformity_sample"
    subprocess.run([exe, "-r", "150", "-png", "-singlefile", "-f", "1", "-l", "1", str(pdf), str(stem)], check=True)
    print(f"wrote {stem}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
