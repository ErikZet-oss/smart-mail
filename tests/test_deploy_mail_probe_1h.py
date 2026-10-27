"""deploy/install.sh mail port probe — Slovak messages; never fails install (Phase 1h-e)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "deploy" / "lib.sh"


def test_1h_probe_mail_ports_slovak_when_unreachable() -> None:
    # Host that refuses connections quickly on all three ports.
    script = f"""
set -euo pipefail
source "{LIB}"
# Force probe_tcp to fail without waiting on DNS of a real host.
probe_tcp() {{ return 1; }}
probe_mail_ports "mail.nameserver.sk"
"""
    out = subprocess.check_output(["bash", "-c", script], text=True)
    assert "IMAP: server nedostupný na porte 993" in out
    assert "SMTP: server nedostupný na porte 465" in out
    assert "Filtre: server nedostupný na porte 4190 – Filtre a Mimo kancelárie nebudú fungovať" in out


def test_1h_probe_mail_ports_ok_messages() -> None:
    script = f"""
set -euo pipefail
source "{LIB}"
probe_tcp() {{ return 0; }}
probe_mail_ports "mail.nameserver.sk"
"""
    out = subprocess.check_output(["bash", "-c", script], text=True)
    assert "IMAP (993/SSL): OK" in out
    assert "SMTP (465/SSL): OK" in out
    assert "Filtre / ManageSieve (4190): OK" in out


def test_1h_default_host_is_mail_nameserver() -> None:
    text = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "mail.nameserver.sk" in text
    assert "mail2.nameserver.sk" not in text
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "mail.nameserver.sk" in env
