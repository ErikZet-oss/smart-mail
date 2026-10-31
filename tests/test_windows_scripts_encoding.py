"""Pilot 2026-10-31: Windows PowerShell 5.1 reads a .ps1 without a UTF-8 BOM as the ANSI code page (cp1250). The
UTF-8 en dash „–“ (E2 80 93) then contains 0x93 = a typographic quote, which PowerShell treats as a string terminator,
so install-bridge.ps1 failed with "The string is missing the terminator". Every .ps1 must start with a UTF-8 BOM."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(p for p in ROOT.joinpath("deploy").rglob("*.ps1"))


def test_there_are_powershell_scripts() -> None:
    assert SCRIPTS


def test_every_powershell_script_has_utf8_bom() -> None:
    missing = [str(p.relative_to(ROOT)) for p in SCRIPTS if not p.read_bytes().startswith(b"\xef\xbb\xbf")]
    assert missing == []


def test_env_file_is_written_without_bom() -> None:
    text = ROOT.joinpath("deploy/bridge-windows/install-bridge.ps1").read_text(encoding="utf-8-sig")
    assert "Set-Content -Path $envFile" not in text
    assert "UTF8Encoding $false" in text
