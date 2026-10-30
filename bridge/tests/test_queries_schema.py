"""Schema drift check inside the bridge suite: every query file validates against the customer's schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from graphql import build_client_schema, parse, validate

from app.gql_client import QUERIES

SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "graphql_schema.json"


@pytest.mark.parametrize("path", sorted(QUERIES.glob("*.graphql")), ids=lambda p: p.stem)
def test_query_matches_schema(path: Path) -> None:
    data = json.loads(SCHEMA.read_text(encoding="utf-8"))
    schema = build_client_schema(data.get("data", data))
    errors = validate(schema, parse(path.read_text(encoding="utf-8")))
    assert not errors, [e.message for e in errors]
    assert "mutation" not in path.read_text(encoding="utf-8").lower()  # Phase 3 is read-only
