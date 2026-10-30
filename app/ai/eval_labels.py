"""The eval label CSV (Erik's answer B on #129): one format for the 17f download/upload and the server CLI.

Excel-friendly for SK Excel: UTF-8 with BOM, `;` separator. The column `kategorie_na_vyber` lists „id – názov“ of
every 17c category (one per row) so the admin knows what to write; `category` accepts the id or the Slovak name
(case and diacritics ignored). The file holds subjects and sender domains of real mail — it is never stored by the
app and never committed; only aggregates are kept.
"""

from __future__ import annotations

import csv
import io
import unicodedata
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.categories import CategoryDef
from app.ai.models import Classification
from app.mail.models import Message

BOM = "﻿"
FIELDS = (
    "message_uuid",
    "received_at",
    "from_domain",
    "subject",
    "predicted",
    "category",
    "language",
    "notes",
    "kategorie_na_vyber",
)
SAMPLE_DEFAULT = 200
MAX_UPLOAD_BYTES = 1_000_000


class LabelError(ValueError):
    """A problem in the label file, with the line number — shown to the admin, never contains mail text."""

    def __init__(self, code: str, line: int | None = None, value: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.line = line
        self.value = value


@dataclass(frozen=True, slots=True)
class Label:
    message_id: uuid.UUID
    category: str
    language: str | None


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(plain.casefold().split())


def category_resolver(categories: Mapping[str, CategoryDef]) -> dict[str, str]:
    """Folded id or Slovak name → category id („Doklady dodávateľov“, „doklady dodavatelov“, „supplier_document“)."""
    out: dict[str, str] = {}
    for cid, c in categories.items():
        out[_fold(c.label_sk)] = cid
    for cid in categories:
        out[_fold(cid)] = cid  # an id wins over a name that happens to look the same
    return out


async def sample_rows(db: AsyncSession, n: int) -> list[dict[str, str]]:
    """n random classified messages — ids, date, sender domain, subject (≤ 200), current prediction. No bodies."""
    rows = (
        await db.execute(
            select(Message, Classification)
            .join(Classification, Classification.message_id == Message.id)
            .where(Classification.status == "done")
            .order_by(func.random())
            .limit(n)
        )
    ).all()
    return [
        {
            "message_uuid": str(message.id),
            "received_at": message.received_at.isoformat() if message.received_at else "",
            "from_domain": (message.from_email or "").rsplit("@", 1)[-1],
            "subject": (message.subject or "")[:200],
            "predicted": cls.category or "",
            "category": "",
            "language": "",
            "notes": "",
        }
        for message, cls in rows
    ]


def sample_csv(rows: Sequence[dict[str, str]], categories: Sequence[CategoryDef]) -> str:
    """The label file as text (BOM + `;`). Category hints fill `kategorie_na_vyber` from the first row down; when
    there are more categories than rows, the rest go to extra rows with no message."""
    legend = [f"{c.id} – {c.label_sk}" for c in categories]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=FIELDS, delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    for i in range(max(len(rows), len(legend))):
        row: dict[str, Any] = dict(rows[i]) if i < len(rows) else {f: "" for f in FIELDS}
        row["kategorie_na_vyber"] = legend[i] if i < len(legend) else ""
        writer.writerow(row)
    return BOM + out.getvalue()


def parse_labels(text: str, categories: Mapping[str, CategoryDef]) -> list[Label]:
    """Rows with a filled `category` (id or Slovak name). `;` or `,` separated (Excel may save either). A wrong
    category or id stops the upload — a typo must not count as an AI error."""
    if len(text.encode("utf-8")) > MAX_UPLOAD_BYTES:
        raise LabelError("eval_file_too_large")
    body = text.removeprefix(BOM)
    first = body.split("\n", 1)[0]
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    reader = csv.DictReader(io.StringIO(body), delimiter=delimiter)
    if not reader.fieldnames or "message_uuid" not in reader.fieldnames or "category" not in reader.fieldnames:
        raise LabelError("eval_bad_header")
    resolve = category_resolver(categories)
    labels: list[Label] = []
    for line, row in enumerate(reader, start=2):
        raw = (row.get("category") or "").strip()
        if not raw:
            continue
        category = resolve.get(_fold(raw))
        if category is None:
            raise LabelError("eval_unknown_category", line, raw[:40])
        try:
            message_id = uuid.UUID((row.get("message_uuid") or "").strip())
        except ValueError as exc:
            raise LabelError("eval_bad_id", line) from exc
        labels.append(Label(message_id, category, (row.get("language") or "").strip().lower() or None))
    if not labels:
        raise LabelError("eval_no_labels")
    return labels
