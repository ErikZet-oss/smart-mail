#!/usr/bin/env python3
"""Server-side eval labeling (Phase 2a skeleton).

Binding (Phase 2 plan B): **no real e-mail in git**, not even encrypted.
This tool is meant to run **on the server** against the live DB / a server-local CSV.

Usage (on the server):
  python tools/eval_label.py --sample 50 --out /var/lib/smartmail/eval/labels.csv
  python tools/eval_label.py --from-csv /var/lib/smartmail/eval/labels.csv --stats

Git holds only fictional smoke fixtures under fixtures/ai/eval_smoke/ for CI.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

CATEGORIES = (
    "inquiry",
    "order",
    "order_change",
    "invoice_request",
    "payment",
    "complaint",
    "shipping",
    "newsletter",
    "spam",
    "internal",
    "other",
)


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


def cmd_sample(n: int, out: Path) -> int:
    """Write a CSV template. Filling it requires server DB access (not implemented in 2a)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        print(f"refusing to overwrite {out}", file=sys.stderr)
        return 2
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["message_uuid", "message_id_header", "category", "language", "notes"],
        )
        writer.writeheader()
        for i in range(n):
            writer.writerow(
                {
                    "message_uuid": "",
                    "message_id_header": "",
                    "category": "",
                    "language": "",
                    "notes": f"fill on server; sample slot {i + 1}",
                }
            )
    print(f"wrote empty template ({n} rows) to {out}")
    print("Allowed categories:", ", ".join(CATEGORIES))
    print("Do not copy real mail bodies into git.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_smoke = sub.add_parser("list-smoke", help="list fictional CI fixtures only")
    p_smoke.set_defaults(fn=lambda _: cmd_list_smoke())

    p_stats = sub.add_parser("stats", help="category counts for a server-local CSV")
    p_stats.add_argument("--from-csv", type=Path, required=True)
    p_stats.set_defaults(fn=lambda a: cmd_stats(a.from_csv))

    p_sample = sub.add_parser("sample", help="write an empty label CSV template (server path)")
    p_sample.add_argument("--sample", type=int, default=50)
    p_sample.add_argument("--out", type=Path, required=True)
    p_sample.set_defaults(fn=lambda a: cmd_sample(a.sample, a.out))

    args = parser.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
