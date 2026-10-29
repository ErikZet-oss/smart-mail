"""Files the backend reads at runtime must be in the Docker image (pilot: Karta rendered dark, logo missing)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _copied_paths() -> list[str]:
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    return [m.group(1) for m in re.finditer(r"^COPY\s+(?!--from)(\S+)\s+\S+", text, re.MULTILINE)]


def test_runtime_design_assets_are_copied_into_the_image() -> None:
    copied = _copied_paths()
    for needed in ("design/tokens.css", "design/brand/logo-smart.png"):
        assert (ROOT / needed).is_file(), needed
        assert any(needed == c or needed.startswith(c.rstrip("/") + "/") for c in copied), f"Dockerfile misses {needed}"


def test_karta_colours_resolve_to_tokens_not_current_color() -> None:
    from app.mail.signature import _token, karta_template

    for name in ("brand-primary-600", "text-primary", "text-secondary", "text-on-primary"):
        assert _token(name).startswith("#"), name
    assert "currentColor" not in karta_template("sk")
