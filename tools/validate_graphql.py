#!/usr/bin/env python3
"""
validate_graphql.py - schema drift check (CLAUDE.md §0.1).

Validates GraphQL operations against the customer's schema (bridge/schema/graphql_schema.json):
  - every *.graphql file under the given paths (default: bridge/app/queries),
  - every ```graphql code block in Markdown files under docs/ (so the specs stay correct too).
Exit code 1 if any operation uses an unknown type, field or argument. Run it in CI.

Usage:  pip install graphql-core
        python tools/validate_graphql.py [--schema bridge/schema/graphql_schema.json] [paths...]
"""
import argparse
import json
import pathlib
import re
import sys

from graphql import build_client_schema, parse, validate
from graphql.error import GraphQLError


def load_schema(path):
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return build_client_schema(data.get("data", data))


def operations(paths):
    for root in paths:
        root = pathlib.Path(root)
        files = [root] if root.is_file() else sorted(root.rglob("*"))
        for f in files:
            if f.suffix == ".graphql":
                yield str(f), f.read_text(encoding="utf-8")
            elif f.suffix == ".md":
                for i, m in enumerate(re.finditer(r"```graphql\n(.*?)```", f.read_text(encoding="utf-8"), re.S)):
                    yield f"{f}#block{i + 1}", m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default="bridge/schema/graphql_schema.json")
    ap.add_argument("paths", nargs="*", default=["bridge/app/queries", "docs"])
    args = ap.parse_args()
    schema = load_schema(args.schema)
    checked, failed = 0, 0
    for name, text in operations([p for p in args.paths if pathlib.Path(p).exists()]):
        checked += 1
        try:
            errors = validate(schema, parse(text))
        except GraphQLError as exc:
            errors = [exc]
        for err in errors:
            failed += 1
            print(f"{name}: {err.message}")
    print(f"{checked} operations checked, {failed} errors")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
