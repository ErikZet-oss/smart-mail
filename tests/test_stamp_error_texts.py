"""Pilot 2026-10-30: uploading a stamp showed only „Zmenu sa nepodarilo uložiť.“ — the error codes of the stamp and
signature check had no Slovak text, so the UI fell back to the generic one. Every code must have its text."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_every_stamp_image_error_code_has_a_slovak_text() -> None:
    source = (ROOT / "app/documents/images.py").read_text(encoding="utf-8")
    codes = set(re.findall(r'SignatureImageError\("([a-z_]+)"\)', source))
    assert {"image_png_required", "image_not_transparent"} <= codes
    texts = json.loads((ROOT / "web/src/i18n/sk.json").read_text(encoding="utf-8"))["settings"]["users"]["errors"]
    assert codes <= set(texts), sorted(codes - set(texts))
