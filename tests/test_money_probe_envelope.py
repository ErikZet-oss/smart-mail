"""Pilot 2026-10-31 (TEST agenda, API 1.15.11): every Money answer is wrapped in
{"PageCount","RowCount","Data","Status","Message","StackTrace"}. The probe stopped at the REST smoke check, printed a
slice of a real invoice to the console and `--orders` / `--branches` overwrote report.md."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("money_probe", ROOT / "tools" / "money_probe.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["money_probe"] = module
    spec.loader.exec_module(module)
    return module


def _env(data: Any, status: int = 1) -> dict[str, Any]:
    return {"PageCount": 1, "RowCount": 1, "Data": data, "Status": status, "Message": "", "StackTrace": ""}


def test_ok_envelope_is_unwrapped_and_error_kept() -> None:
    probe = _probe()
    assert probe._unwrap(_env([{"ID": "x"}])) == [{"ID": "x"}]
    assert probe._unwrap(_env({"Version": "1"})) == {"Version": "1"}
    err = _env(None, status=0)
    assert probe._unwrap(err) is err
    assert probe._unwrap([1, 2]) == [1, 2]


class _Http:
    def __init__(self, res: Any) -> None:
        self.res = res

    def request(self, *_: Any, **__: Any) -> tuple[int, str, Any, int]:
        return 200, "application/json", self.res, 5


def test_gql_reads_unwrapped_root_and_reports_error_status() -> None:
    probe = _probe()
    _, data, errors, _ = probe.gql(_Http({"Version": "1.15.11.7730"}), "{ Version }")
    assert data == {"Version": "1.15.11.7730"} and errors is None
    _, data, errors, _ = probe.gql(_Http(_env(None, status=0)), "{ Version }")
    assert data is None and errors
    _, data, errors, _ = probe.gql(_Http({"data": {"Version": "1"}}), "{ Version }")
    assert data == {"Version": "1"}


def test_smoke_never_prints_values() -> None:
    text = (ROOT / "tools" / "money_probe.py").read_text(encoding="utf-8")
    assert "body: {str(res)" not in text


def test_orders_and_branches_do_not_overwrite_report_md() -> None:
    text = (ROOT / "tools" / "money_probe.py").read_text(encoding="utf-8")
    assert "write_orders_report()\n        write_report()" not in text
    assert "write_branches_report()\n        write_report()" not in text
