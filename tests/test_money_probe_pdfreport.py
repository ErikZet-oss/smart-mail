"""#222 `money_probe.py --pdfreport`: read-only, and the output never holds the document number, ID or PDF content.
All values are fictional."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.test_money_probe_envelope import _probe

NUMBER = "DV26FIKT042"
RECORD = "6b1f0000-0000-4000-8000-00000000f1c7"
SECRET_PDF = b"%PDF-1.4 SECRET-CUSTOMER-NAME Fiktivna s.r.o."


class _Http:
    def __init__(self, design_required: bool) -> None:
        self.design_required = design_required
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **__: Any) -> tuple[int, str, Any, int]:
        assert method == "POST" and url == "/graphql"  # only the GraphQL lookup, never a write
        return 200, "application/json", {"IssuedDeliveryNotes": [{"ID": RECORD, "CisloDokladu": NUMBER}]}, 5

    def get(self, path: str, params: Any = None, raw: bool = False) -> tuple[int, str, Any, int]:
        self.calls.append((path, dict(params or {})))
        if self.design_required and "designid" not in (params or {}):
            return 400, "application/json", b'{"Message":"designid"}', 7
        return 200, "application/pdf", SECRET_PDF, 9


@pytest.mark.parametrize("design_required", [False, True])
def test_222_pdfreport_probe_records_only_technical_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, design_required: bool
) -> None:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    probe.pdfreport_report["steps"] = {}
    http = _Http(design_required)
    out = probe.pdfreport_probe(http, NUMBER, "12", "34")
    assert [p for p, _ in http.calls] == ["/pdfreport", "/pdfreport"]
    assert http.calls[0][1] == {"objectname": "issueddeliverynote", "id": RECORD, "reportid": "12", "designid": "34"}
    assert "designid" not in http.calls[1][1]
    assert out["with_designid"]["is_pdf"] is True and out["with_designid"]["content_type"] == "application/pdf"
    assert out["designid_required"] is design_required
    probe.write_pdfreport_report()
    for name in ("pdfreport.md", "pdfreport.json"):
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert NUMBER not in text and RECORD not in text and "SECRET" not in text and "Fiktivna" not in text


def test_222_pdfreport_probe_without_settings_does_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    probe.pdfreport_report["steps"] = {}
    assert probe.pdfreport_probe(_Http(False), None, None, None) == {"configured": False}
