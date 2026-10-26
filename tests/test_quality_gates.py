"""Repository-level quality gates (CLAUDE.md §0.1, §10), run in CI from Phase 0 so later phases cannot skip them."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# --- no floats for money or quantities --------------------------------------------------------------
FLOAT_BANNED_DIRS = ["app/orders", "app/purchasing", "app/offers", "bridge/app"]
FLOAT_CALL = re.compile(r"(?<![\w.])float\s*\(")


def _python_files(rel: str) -> list[Path]:
    base = ROOT / rel
    return sorted(base.rglob("*.py")) if base.exists() else []


@pytest.mark.parametrize("rel", FLOAT_BANNED_DIRS)
def test_no_float_in_money_code(rel: str) -> None:
    offenders = [
        f"{f.relative_to(ROOT)}:{n}"
        for f in _python_files(rel)
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if FLOAT_CALL.search(line.split("#", 1)[0])
    ]
    assert not offenders, "float( is forbidden here — use Decimal (CLAUDE.md §0.1): " + ", ".join(offenders)


def test_float_gate_detects_violation() -> None:
    assert FLOAT_CALL.search("price = float(x)")
    assert not FLOAT_CALL.search("Decimal(x)  # never float")


# --- design tokens are copied, never edited by hand ---------------------------------------------------
def test_web_tokens_equal_design_tokens() -> None:
    src = (ROOT / "design" / "tokens.css").read_bytes()
    dst = ROOT / "web" / "src" / "styles" / "tokens.css"
    assert dst.exists(), "copy design/tokens.css to web/src/styles/tokens.css (make tokens)"
    assert dst.read_bytes() == src, "web/src/styles/tokens.css differs from design/tokens.css — run `make tokens`"


# --- GraphQL schema drift ------------------------------------------------------------------------------
def test_graphql_operations_match_money_schema() -> None:
    spec = importlib.util.spec_from_file_location("validate_graphql", ROOT / "tools" / "validate_graphql.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from graphql import parse, validate

    schema = mod.load_schema(ROOT / "bridge" / "schema" / "graphql_schema.json")
    paths = [p for p in (ROOT / "bridge" / "app" / "queries", ROOT / "docs") if p.exists()]
    errors = [f"{name}: {err.message}" for name, text in mod.operations(paths) for err in validate(schema, parse(text))]
    assert not errors, "\n".join(errors)


# --- fixtures stay fictional -------------------------------------------------------------------------
def test_fixtures_are_marked_fictional() -> None:
    for f in (ROOT / "fixtures" / "documents").glob("*.json"):
        assert "FICTIONAL" in f.read_text(encoding="utf-8")[:400], f"{f.name} must start with a FICTIONAL _comment"
