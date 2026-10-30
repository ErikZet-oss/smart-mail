#!/usr/bin/env python3
"""Server-side eval labeling and `make eval` (Phase 2f).

Binding (Phase 2 plan B): **no real e-mail in git**, not even encrypted.
This tool is meant to run **on the server** against the live DB / a server-local CSV.

Usage (on the server; inside the app container use `python -m app.ai.eval_cli` — `make eval`):
  python tools/eval_label.py sample --sample 200 --out /var/lib/smartmail/eval/labels.csv
  python tools/eval_label.py stats --from-csv /var/lib/smartmail/eval/labels.csv
  python tools/eval_label.py run --from-csv /var/lib/smartmail/eval/labels.csv [--live] [--save]

Git holds only fictional smoke fixtures under fixtures/ai/eval_smoke/ for CI.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _smoke_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / "ai" / "eval_smoke"


def cmd_list_smoke() -> int:
    root = _smoke_dir()
    if not root.is_dir():
        print(f"missing smoke fixtures: {root}", file=sys.stderr)
        return 1
    for path in sorted(root.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        print(f"{path.name}\t{data.get('category', '?')}\t{data.get('subject', '')[:60]}")
    return 0


def cmd_stats(csv_path: Path) -> int:
    if not csv_path.is_file():
        print(f"CSV not found: {csv_path}", file=sys.stderr)
        print("Create labels on the server; do not commit real mail.", file=sys.stderr)
        return 1
    counts: dict[str, int] = {}
    with csv_path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cat = (row.get("category") or "other").strip()
            counts[cat] = counts.get(cat, 0) + 1
    total = sum(counts.values())
    print(f"rows={total}")
    for cat in sorted(counts):
        print(f"  {cat}: {counts[cat]}")
    return 0


def cmd_server(argv: list[str]) -> int:
    """sample / run need the database: delegate to the server CLI (app/ai/eval_cli.py)."""
    import asyncio

    sys.path.insert(0, str(REPO_ROOT))
    from app.ai.eval_cli import main as eval_main

    return asyncio.run(eval_main(argv))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_smoke = sub.add_parser("list-smoke", help="list fictional CI fixtures only")
    p_smoke.set_defaults(fn=lambda _: cmd_list_smoke())

    p_stats = sub.add_parser("stats", help="category counts for a server-local CSV")
    p_stats.add_argument("--from-csv", type=Path, required=True)
    p_stats.set_defaults(fn=lambda a: cmd_stats(a.from_csv))

    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] in (["sample"], ["run"]):
        return cmd_server(argv)
    sub.add_parser("sample", help="write a label CSV of N random classified messages (server, needs the DB)")
    sub.add_parser("run", help="score the AI against a labeled CSV (server, needs the DB)")

    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
