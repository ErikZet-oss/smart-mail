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
    monkeypatch.delenv("PROBE_DL_COMPARE_NUMBER", raising=False)
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    probe.koncept_report["steps"] = {}
    http = _Http()
    probe.koncept_probe(http, "309990001")
    probe.write_koncept_report()
    steps = probe.koncept_report["steps"]
    assert steps["Stav"] == 1 and steps["Popis_contains_SMPROBE"] is True
    assert steps["header_fields"]["Firma_ID"] == "set" and steps["items"] == 1
    assert steps["last_300_Stav"] == {"0": 3, "1": 1}
    assert steps["flags_that_vary_in_last_300"]["Zauctovano"] == {"True": 3, "False": 1}
    md = (tmp_path / "koncept.md").read_text(encoding="utf-8")
    assert FIRMA not in md and "309990001" not in md
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    sch = build_client_schema(schema.get("data", schema))
    for q in http.queries:
        assert validate(sch, parse(q)) == []


def test_koncept_probe_compares_with_a_normal_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    monkeypatch.setenv("PROBE_DL_COMPARE_NUMBER", "309990002")
    probe.koncept_report["steps"] = {}

    class Http(_Http):
        def request(self, method: str, url: str, data: bytes = b"", **kw: Any) -> tuple[int, str, Any, int]:
            body = json.loads(data)
            if body.get("variables", {}).get("f") == "CisloDokladu~eq~309990002":
                doc = {"CisloDokladu": "309990002", "Stav": 0, "Faze": 1, "Zauctovano": True, "Firma_ID": FIRMA}
                return 200, "application/json", {"data": {"ReceivedDeliveryNotes": [doc]}}, 3
            return super().request(method, url, data, **kw)

    probe.koncept_probe(Http(), "309990001")
    diff = probe.koncept_report["steps"]["differs_from_normal_note"]
    assert diff["Zauctovano"] == {"koncept": False, "normal": True}
    assert "Firma_ID" not in diff  # set on both, IDs never compared by value


def test_koncept_probe_shows_the_vat_difference_of_header_and_first_stock_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pilot 2026-11-24: the FABORY koncept came without VAT — the probe shows which VAT field differs."""
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    monkeypatch.setenv("PROBE_DL_COMPARE_NUMBER", "309990002")
    probe.koncept_report["steps"] = {}
    rate_a, rate_b = "a0000000-0000-4000-8000-000000000001", "a0000000-0000-4000-8000-000000000002"
    koncept = {
        "CisloDokladu": "309990001",
        "ZpusobVypoctuDPH": 0,
        "SumaDan": 0,
        "Firma_ID": FIRMA,
        "Polozky": [{"TypObsahu": 1, "DphSazba": 0, "SazbaDPH_ID": rate_a, "DruhSazbyDPH": 2, "JednCena": 1.5}],
    }
    normal = {
        "CisloDokladu": "309990002",
        "ZpusobVypoctuDPH": 1,
        "SumaDan": 81.19,
        "Firma_ID": "f0000000-0000-4000-8000-000000000002",
        "Polozky": [
            {"TypObsahu": 3, "DphSazba": 0},
            {"TypObsahu": 1, "DphSazba": 23, "SazbaDPH_ID": rate_b, "DruhSazbyDPH": 2, "JednCena": 9.9},
        ],
    }

    class Http(_Http):
        def request(self, method: str, url: str, data: bytes = b"", **kw: Any) -> tuple[int, str, Any, int]:
            f = json.loads(data).get("variables", {}).get("f")
            if f in ("CisloDokladu~eq~309990001", "CisloDokladu~eq~309990002"):
                doc = koncept if f.endswith("1") else normal
                return 200, "application/json", {"data": {"ReceivedDeliveryNotes": [doc]}}, 3
            return super().request(method, url, data, **kw)

    probe.koncept_probe(Http(), "309990001")
    probe.write_koncept_report()
    steps = probe.koncept_report["steps"]
    assert steps["differs_from_normal_note"]["ZpusobVypoctuDPH"] == {"koncept": 0, "normal": 1}
    assert steps["differs_from_normal_note"]["SumaDan"] == {"koncept": 0, "normal": 81.19}
    assert "Firma_ID" not in steps["differs_from_normal_note"]
    line = steps["first_stock_line_differs"]
    assert line["DphSazba"] == {"koncept": 0, "normal": 23}
    assert line["SazbaDPH_ID"] == {"koncept": "set", "normal": "set (different ID)"}
    assert "DruhSazbyDPH" not in line and "JednCena" not in line  # equal / not a VAT field
    md = (tmp_path / "koncept.md").read_text(encoding="utf-8")
    assert rate_a not in md and rate_b not in md and FIRMA not in md
