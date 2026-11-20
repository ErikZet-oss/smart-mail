"""`money_probe.py --article-write-test` (D32): exactly two hidden cards after typing ZALOZIT, never retried, never
deleted, codebook IDs never in the report. All values are fictional."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from graphql import build_client_schema, parse, validate

from tests.test_money_probe_envelope import _probe

ROOT = Path(__file__).resolve().parents[1]
GROUP = "9a000000-0000-4000-8000-0000000000aa"


class _Http:
    def __init__(self, fail_variant: bool = False) -> None:
        self.mutations: list[dict[str, Any]] = []
        self.cards: dict[str, dict[str, Any]] = {}
        self.fail_variant = fail_variant

    def request(self, method: str, url: str, data: bytes = b"", **__: Any) -> tuple[int, str, Any, int]:
        assert method == "POST" and url == "/graphql"
        body = json.loads(data)
        q, v = body["query"], body["variables"]
        assert "DeleteArticle" not in q and "EditArticle" not in q
        if q.startswith("mutation"):
            a = v["a"]
            self.mutations.append(a)
            if self.fail_variant and a.get("NadrazenyArtikl_ID"):
                return 200, "application/json", {"errors": [{"message": "boom"}]}, 4
            row = {
                "ID": f"id-{len(self.cards)}",
                "Group_ID": GROUP,
                "HlavniJednotka": {"Kod": "ks"},
                "SeznamJednotek": [{"Kod": "ks"}],
                "SazbyDPH": [{"SazbaVstup": 23, "SazbaVystup": 23}],
                **a,
            }
            self.cards[a["Katalog"]] = row
            return 200, "application/json", {"data": {"CreateArticle": {"ID": row["ID"], "Katalog": a["Katalog"]}}}, 4
        if "MerpGroups" in q:
            return 200, "application/json", {"data": {"MerpGroups": [{"ID": GROUP, "Nazev": "Nezaradené"}]}}, 2
        f = v.get("f", "")
        if f.startswith("Katalog~eq~"):
            found = self.cards.get(f.split("~eq~", 1)[1])
            return 200, "application/json", {"data": {"Articles": [found] if found else []}}, 2
        return 200, "application/json", {"data": {"Articles": []}}, 2


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typed: str, http: _Http) -> Any:
    probe = _probe()
    monkeypatch.setattr(probe, "OUT_DIR", str(tmp_path))
    monkeypatch.setattr("builtins.input", lambda *_: typed)
    monkeypatch.setenv("PROBE_ARTICLE_TEST_CATALOG", "SMPROBE01")
    probe.article_write_report["steps"] = {}
    probe.article_write_test(http)
    probe.write_article_write_report()
    return probe


def test_d32_article_write_test_needs_zalozit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = _Http()
    probe = _run(tmp_path, monkeypatch, "ano", http)
    assert http.mutations == [] and probe.article_write_report["steps"]["refused"] == "cancelled by user"


def test_d32_article_write_test_creates_two_hidden_cards_and_reports_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    http = _Http()
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert [m["Katalog"] for m in http.mutations] == ["SMPROBE01", "SMPROBE0100010"]
    assert all(m["Hidden"] is True and "SMID:" in m["Poznamka"] for m in http.mutations)
    assert http.mutations[1]["NadrazenyArtikl_ID"] == "id-0"
    steps = probe.article_write_report["steps"]
    assert steps["main_card"]["group"] == "Nezaradené" and steps["main_card"]["main_unit"] == "ks"
    assert steps["variant_card"]["linked_to_main"] is True
    assert steps["delete_in_money"] == ["SMPROBE01", "SMPROBE0100010"]
    md = (tmp_path / "article_write.md").read_text(encoding="utf-8")
    assert GROUP not in md and "id-0" not in md  # IDs are never written


def test_d32_failed_create_is_never_retried(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = _Http(fail_variant=True)
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert len(http.mutations) == 2  # main + one variant attempt, no retry
    assert probe.article_write_report["steps"]["variant_created"] is False
    assert probe.article_write_report["steps"]["delete_in_money"] == ["SMPROBE01"]


def test_d32_existing_catalog_refuses_before_any_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    http = _Http()
    http.cards["SMPROBE01"] = {"ID": "x", "Katalog": "SMPROBE01"}
    probe = _run(tmp_path, monkeypatch, "ZALOZIT", http)
    assert http.mutations == [] and "already exists" in probe.article_write_report["steps"]["refused"]


def test_d32_probe_queries_are_valid_against_the_customer_schema() -> None:
    src = (ROOT / "tools/money_probe.py").read_text(encoding="utf-8")
    m = re.search(r'ARTICLE_READ = """(.*?)"""', src, re.S)
    assert m
    schema = json.loads((ROOT / "bridge/schema/graphql_schema.json").read_text(encoding="utf-8"))
    sch = build_client_schema(schema.get("data", schema))
    for q in (
        "query($f:String){ Articles(Filter:$f, Count:1){ " + m.group(1) + " } }",
        "mutation($a: ArticleInput!){ CreateArticle(Article:$a){ ID Katalog } }",
        "query($o:String!){ MerpGroups(ObjectName:$o, Count:2000){ ID Nazev } }",
    ):
        assert validate(sch, parse(q)) == []
