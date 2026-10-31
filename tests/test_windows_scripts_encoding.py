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


def test_bridge_virtualenv_uses_python_readable_by_local_service() -> None:
    """Pilot 2026-10-31: the venv pointed at C:\\Users\\smartadmin\\…\\Python312 and the LocalService account could not
    start it („No Python at …“, NSSM SERVICE_PAUSED). Both scripts must build the venv from uv's Python in
    C:\\SmartMail\\python and grant LocalService read access to it."""
    for name in ("install-bridge.ps1", "update-bridge.ps1"):
        text = ROOT.joinpath("deploy/bridge-windows", name).read_text(encoding="utf-8-sig")
        assert "C:\\SmartMail\\python" in text, name
        assert "uv python install 3.12" in text, name
        assert "--managed-python" in text, name
        assert "$env:UV_PYTHON = $bridgePython" in text, name
        assert "LOCAL SERVICE:(OI)(CI)RX" in text, name


def test_install_does_not_require_winget_for_cloudflared() -> None:
    text = ROOT.joinpath("deploy/bridge-windows/install-bridge.ps1").read_text(encoding="utf-8-sig")
    assert "cloudflared-windows-amd64.msi" in text
    assert "winget install --id Cloudflare.cloudflared" not in text
