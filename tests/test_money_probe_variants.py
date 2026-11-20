"""`money_probe.py --variants`: read-only (only GraphQL reads), catalog pattern of main card + variants, and the
schema check whether variant parameters can be written. All articles are fictional."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from graphql import build_client_schema, parse, validate

from tests.test_money_probe_envelope import _probe

ROOT = Path(__file__).resolve().parents[1]
MAIN_ID = "a0000000-0000-4000-8000-000000000001"


def _art(i: int, catalog: str, name: str, size: str | None, parent: str | None) -> dict[str, Any]:
    return {
        "ID": f"a0000000-0000-4000-8000-{i:012d}",
        "Deleted": False,
        "Hidden": False,
        "Kod": f"K{i}",
        "Katalog": catalog,
        "Nazev": name,
        "Varianta": size,
        "NadrazenyArtikl_ID": parent,
        "Parent_ID": None,
        "Group_ID": "g-1",
        "HlavniJednotka_ID": "u-ks",
        "TypArtiklu": "Jednoduchy",
        "PripojitParametryKeKatalogu": True,
        "Parametry": [
            {"Poradi": 1, "TextovaHodnota": size, "Hodnota_ID": "h", "Parametr": {"Nazev": "Rozmer", "Variantni": True}}
        ]
        if size
        else [],
    }


MAIN = _art(1, "9990001", "Tyč závitová DIN 976 4.8 ZN", None, None)
VARIANTS = [_art(10 + n, f"999000100{n:02d}", f"tyč záv. M{n}x2000 4.8 ZN", f"M{n}", MAIN_ID) for n in (8, 10, 12)]


class _Http:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, data: bytes = b"", **__: Any) -> tuple[int, str, Any, int]:
        assert method == "POST" and url == "/graphql"  # reads only, never a mutation
        body = json.loads(data)
        assert "mutation" not in body["query"]
        self.calls.append(body)
        f = body["variables"]["f"]
        if f == "Katalog~eq~9990001":
            return 200, "application/json", {"Articles": [MAIN]}, 3
        if f == f"NadrazenyArtikl_ID~eq~{MAIN['ID']}":
            return 200, "application/json", {"Articles": VARIANTS}, 3
        return 200, "application/json", {"Articles": []}, 3


def test_variants_probe_reads_pattern_and_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    (tmp_path / "graphql_schema_raw.txt").write_text(json.dumps(schema), encoding="utf-8")
    probe.variants_report.update({"schema": {}, "cards": []})
    http = _Http()
    probe.variants_probe(http, "9990001, 0000000")
    card = probe.variants_report["cards"][0]
    assert card["variant_count"] == 3 and card["catalog_prefix_is_main"] == 3
    assert card["suffix_lengths"] == {"4": 3} and card["duplicate_catalogs"] == []
    assert card["shared_with_main"]["Group_ID"] == 3
    assert card["sample"][0]["suffix"] == "0008" and card["sample"][0]["parameters"][0]["value"] == "M8"
    assert probe.variants_report["cards"][1]["found"] is False
    sch = probe.variants_report["schema"]
    assert sch["CreateArticle"] is True and sch["ArticleInput_NadrazenyArtikl_ID"] is True
    assert sch["ArticleInput_parameter_fields"] == []  # the customer's schema cannot write variant parameters
    probe.write_variants_report()
    md = (tmp_path / "variants.md").read_text(encoding="utf-8")
    assert "| 99900010010 | 0010 | tyč záv. M10x2000 4.8 ZN | M10 | Rozmer=M10 |" in md


def test_variants_query_is_valid_against_the_customer_schema() -> None:
    src = (ROOT / "tools/money_probe.py").read_text(encoding="utf-8")
    m = re.search(r'VARIANT_FIELDS = """(.*?)"""', src, re.S)
    assert m
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    query = "query($f:String){ Articles(Filter:$f){ " + m.group(1) + " } }"
    assert validate(build_client_schema(schema.get("data", schema)), parse(query)) == []
