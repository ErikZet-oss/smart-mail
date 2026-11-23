"""`money_probe.py --dl-koncept-write-test`: one koncept note (Faze 0, Schvaleno false) after ZALOZIT, copied from the
koncept template, never retried, IDs never printed. All values fictional."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from graphql import build_client_schema, parse, validate

from tests.test_money_probe_envelope import _probe

ROOT = Path(__file__).resolve().parents[1]
ART, WH, SERIES = (f"a0000000-0000-4000-8000-00000000000{i}" for i in (1, 2, 3))
TEMPLATE = {
    "ID": "t",
    "CisloDokladu": "309990001",
    "Faze": 0,
    "Schvaleno": False,
    "Stav": 0,
    "CiselnaRada_ID": SERIES,
    "Stredisko_ID": "c",
    "Polozky": [
        {"Mnozstvi": 100, "JednCena": 0.0047, "TypCeny": 0, "ObsahPolozky": {"Artikl_ID": ART, "Sklad_ID": WH}}
    ],
}


class _Http:
    def __init__(self, template: dict[str, Any], fail: bool = False) -> None:
        self.template, self.fail = template, fail
        self.mutations: list[dict[str, Any]] = []
        self.created: dict[str, Any] | None = None
        self.queries: list[str] = []

    def request(self, method: str, url: str, data: bytes = b"", **__: Any) -> tuple[int, str, Any, int]:
        body = json.loads(data)
        q, v = body["query"], body.get("variables") or {}
        self.queries.append(q)
        assert "Delete" not in q and "Edit" not in q
        if q.startswith("mutation"):
            self.mutations.append(v["d"])
            if self.fail:
                return 200, "application/json", {"errors": [{"message": "boom"}]}, 5
            self.created = {
                **v["d"],
                "ID": "n",
                "CisloDokladu": "309990777",
                "Stav": 0,
                "Polozky": [{"ObsahPolozky": v["d"]["Polozky"][0]["ObsahPolozky"]}],
            }
            return 200, "application/json", {"data": {"CreateReceivedDeliveryNote": {"ID": "n"}}}, 5
        f = v.get("f", "")
        if f == "CisloDokladu~eq~309990001":
            return 200, "application/json", {"data": {"ReceivedDeliveryNotes": [self.template]}}, 2
        if f.startswith("Poznamka~ct~"):
            return (
                200,
                "application/json",
                {"data": {"ReceivedDeliveryNotes": [self.created] if self.created else []}},
                2,
            )
        return 200, "application/json", {"data": {"ReceivedDeliveryNotes": []}}, 2


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: str, http: _Http) -> Any:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda *_: typed)
    probe.dl_koncept_report["steps"] = {}
    probe.dl_koncept_write_test(http, "309990001")
    probe.write_dl_koncept_report()
    return probe


def test_dl_koncept_write_needs_zalozit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = _Http(TEMPLATE)
    _run(tmp_path, monkeypatch, "ano", http)
    assert http.mutations == []


def test_dl_koncept_write_creates_one_koncept_copied_from_the_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    http = _Http(TEMPLATE)
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert len(http.mutations) == 1
    m = http.mutations[0]
    assert m["Faze"] == 0 and m["Schvaleno"] is False and m["Nazev"].startswith("Smartmail")
    assert "SMID:" in m["Poznamka"] and m["CiselnaRada_ID"] == SERIES
    assert m["Polozky"] == [
        {"ObsahPolozky": {"Artikl_ID": ART, "Sklad_ID": WH}, "Mnozstvi": 1, "JednCena": 0.0047, "TypCeny": 0}
    ]
    steps = probe.dl_koncept_report["steps"]
    assert steps["number"] == "309990777" and steps["same_article_and_warehouse"] is True
    md = (tmp_path / "dl_koncept_write.md").read_text(encoding="utf-8")
    assert ART not in md and SERIES not in md
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    sch = build_client_schema(schema.get("data", schema))
    for q in set(http.queries):
        assert validate(sch, parse(q)) == []


def test_dl_koncept_write_never_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = _Http(TEMPLATE, fail=True)
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert len(http.mutations) == 1 and probe.dl_koncept_report["steps"]["created"] is False


def test_dl_koncept_write_refuses_a_template_that_is_not_a_koncept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    http = _Http({**TEMPLATE, "Faze": 1, "Schvaleno": True})
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert http.mutations == [] and "not a koncept" in probe.dl_koncept_report["steps"]["refused"]
    assert re.search(r"refused", (tmp_path / "dl_koncept_write.md").read_text(encoding="utf-8"))
