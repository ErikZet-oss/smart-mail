"""`money_probe.py --koncept` (read-only): Stav of a draft note, writable field names, IDs never printed. Fictional."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from graphql import build_client_schema, parse, validate

from tests.test_money_probe_envelope import _probe

ROOT = Path(__file__).resolve().parents[1]
FIRMA = "f0000000-0000-4000-8000-000000000001"


class _Http:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def request(self, method: str, url: str, data: bytes = b"", **__: Any) -> tuple[int, str, Any, int]:
        assert method == "POST" and url == "/graphql"
        body = json.loads(data)
        assert "mutation" not in body["query"]
        self.queries.append(body["query"])
        if "Filter" in body["query"]:
            doc = {
                "CisloDokladu": "309990001",
                "Nazev": "SMPROBE koncept",
                "Stav": 1,
                "Vyrizeno": 0,
                "Zauctovano": False,
                "Firma_ID": FIRMA,
                "Polozky": [{"Mnozstvi": 1, "Nazev": "x"}],
            }
            return 200, "application/json", {"data": {"ReceivedDeliveryNotes": [doc]}}, 3
        rows = [{"Stav": 0, "Vyrizeno": 2, "Zauctovano": True}] * 3 + [{"Stav": 1, "Vyrizeno": 0, "Zauctovano": False}]
        return 200, "application/json", {"data": {"ReceivedDeliveryNotes": rows}}, 3


def test_koncept_probe_reports_stav_and_never_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    probe.koncept_report["steps"] = {}
    http = _Http()
    probe.koncept_probe(http, "309990001")
    probe.write_koncept_report()
    steps = probe.koncept_report["steps"]
    assert steps["Stav"] == 1 and steps["Popis_contains_SMPROBE"] is True
    assert steps["header_fields"]["Firma_ID"] == "set" and steps["items"] == 1
    assert steps["last_300_Stav"] == {"0": 3, "1": 1}
    md = (tmp_path / "koncept.md").read_text(encoding="utf-8")
    assert FIRMA not in md and "309990001" not in md
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    sch = build_client_schema(schema.get("data", schema))
    for q in http.queries:
        assert validate(sch, parse(q)) == []
