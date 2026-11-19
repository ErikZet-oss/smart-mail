"""Pilot 2026-11-19: /pdfreport answered 404 for issued delivery notes. The probe tries a read-only matrix
(invoice control, objectname spellings, path prefixes, REST route) and never writes document numbers, IDs or PDFs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
DL_ID = "3098b7f1-019b-4c2b-9338-104b9a130d66"
INV_ID = "8952b0de-1a15-41b2-ad74-876c425db883"


def _probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("money_probe_matrix", ROOT / "tools" / "money_probe.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["money_probe_matrix"] = module
    spec.loader.exec_module(module)
    return module


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def request(
        self, method: str, url: str, data: Any = None, headers: Any = None, raw: bool = False, timeout: int = 60
    ) -> tuple[int, str, bytes, int]:
        self.calls.append(url)
        if "/IssuedInvoice/" in url:
            return 200, "application/pdf", b"%PDF-1.7 ...", 5
        if "/pdfreport" in url and "objectname=issuedinvoice" in url:
            return 200, "application/pdf", b"%PDF-1.4 ...", 5
        msg = f'{{"Message":"Report {DL_ID} for document 312602366 not found"}}'.encode()
        return 404, "application/json; charset=utf-8", msg, 3

    def get(self, path: str, params: dict[str, Any] | None = None, raw: bool = False) -> tuple[int, str, bytes, int]:
        from urllib.parse import urlencode

        return self.request("GET", path + ("?" + urlencode(params) if params else ""), raw=raw)


def test_matrix_control_and_masking(monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _probe()
    monkeypatch.setenv("PROBE_INVOICE_NUMBER", "FV2026/0001")
    monkeypatch.setenv("PROBE_REPORT_ID", "2b96e32f-a9c7-4dd6-9d80-31d9a35248fc")
    monkeypatch.setattr(probe, "gql", lambda http, q, v=None: (200, {"IssuedInvoices": [{"ID": INV_ID}]}, None, 1))
    out: dict[str, Any] = {}
    probe.pdfreport_matrix(FakeHttp(), DL_ID, "1dc7f57d-85d7-4b2a-866f-2639435c8bcd", None, out)
    m = out["matrix"]
    assert m["A1 REST IssuedInvoice Report (known to work)"]["is_pdf"] is True
    assert m["A2 /pdfreport issuedinvoice"]["is_pdf"] is True
    assert m["B objectname=IssuedDeliveryNote"]["status"] == 404
    text = repr(m)
    assert DL_ID not in text and INV_ID not in text and "312602366" not in text
    assert "<guid>" in m["B objectname=IssuedDeliveryNote"]["error_text"]
    assert "D REST v2.0/IssuedDeliveryNote/Report" in m
