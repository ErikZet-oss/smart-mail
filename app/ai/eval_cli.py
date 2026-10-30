"""`make eval` on the server (Phase 2 plan B): label a sample of real mail in a server-local CSV, then score the AI.

    python -m app.ai.eval_cli sample --sample 200 --out /var/lib/smartmail/eval/labels.csv
    (an admin fills the `category` column — and `language` if wanted — on the server)
    python -m app.ai.eval_cli run --from-csv /var/lib/smartmail/eval/labels.csv            # stored classifications
    python -m app.ai.eval_cli run --from-csv … --live --limit 200 --save                  # classify again (paid)

The CSV holds real mail data, so it stays on the server: the tool refuses to write it inside the repository and
creates it readable by the owner only. Reports and the 17f summary carry category codes and counts only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  (register every table)
from app.ai.budget import budget_allows_call
from app.ai.categories import CategoryDef
from app.ai.category_settings import category_lookup, load_category_data, prompt_categories
from app.ai.classify import classify_message
from app.ai.eval import ACCURACY_GATE, SECTION_EVAL, EvalReport, EvalRow, evaluate, format_report
from app.ai.eval_labels import SAMPLE_DEFAULT, Label, LabelError, parse_labels, sample_csv, sample_rows
from app.ai.models import AiRun, Classification
from app.ai.org_settings import load_ai_limits, save_org_section
from app.ai.pricing import estimate_purpose_cost_usd
from app.ai.provider import AnthropicLLMProvider, LLMProvider, get_llm_provider
from app.ai.service import daily_spend_usd
from app.core.config import Settings, get_settings
from app.mail.models import Attachment, Message

REPO_ROOT = Path(__file__).resolve().parents[2]


class EvalError(Exception):
    """A user error on the server console (bad path, bad CSV) — printed, exit code 2."""


def _check_out_path(out: Path) -> None:
    resolved = out.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise EvalError(f"refusing to write real mail data inside the repository: {out}")
    if out.exists():
        raise EvalError(f"refusing to overwrite {out}")


async def sample(db: AsyncSession, n: int, out: Path) -> int:
    """Write the label file (same format as the 17f download) readable by the owner only. Returns the row count."""
    _check_out_path(out)
    rows = await sample_rows(db, n)
    text = sample_csv(rows, prompt_categories(await load_category_data(db)))
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return len(rows)


def read_labels(path: Path, categories: dict[str, CategoryDef]) -> list[Label]:
    if not path.is_file():
        raise EvalError(f"CSV not found: {path}")
    try:
        return parse_labels(path.read_text(encoding="utf-8"), categories)
    except LabelError as exc:
        where = f"line {exc.line}: " if exc.line else ""
        raise EvalError(f"{where}{exc.code}" + (f" {exc.value!r}" if exc.value else "")) from exc


async def _stored(db: AsyncSession, labels: list[Label]) -> list[EvalRow]:
    found = {
        cls.message_id: cls
        for cls in (
            await db.scalars(
                select(Classification).where(
                    Classification.message_id.in_([lb.message_id for lb in labels]),
                    Classification.status == "done",
                )
            )
        ).all()
    }
    return [
        EvalRow(
            lb.category,
            found[lb.message_id].category if lb.message_id in found else None,
            lb.language,
            found[lb.message_id].language if lb.message_id in found else None,
        )
        for lb in labels
    ]


async def _live(
    db: AsyncSession, settings: Settings, provider: LLMProvider, labels: list[Label]
) -> tuple[list[EvalRow], Decimal, int]:
    """Classify each labeled message again with today's prompt and categories. Every paid call is an `ai_runs` row
    (purpose `eval`) and counts against the daily budget; the run stops when the budget is used up."""
    model = (settings.llm_model_classify or "").strip()
    if not model or not isinstance(provider, AnthropicLLMProvider):
        raise EvalError("--live needs a configured LLM provider and LLM_MODEL_CLASSIFY")
    categories = prompt_categories(await load_category_data(db))
    budget = (await load_ai_limits(db, settings)).budget_usd
    estimate = estimate_purpose_cost_usd(model, "classify")
    spent = await daily_spend_usd(db)
    cost = Decimal("0")
    rows: list[EvalRow] = []
    skipped = 0
    for lb in labels:
        message = await db.get(Message, lb.message_id)
        if message is None:
            rows.append(EvalRow(lb.category, None, lb.language, None))
            continue
        if not budget_allows_call(spent_usd=spent, estimate_usd=estimate, budget_usd=budget):
            skipped += 1
            continue
        atts = (await db.scalars(select(Attachment).where(Attachment.message_id == message.id))).all()
        outcome = await classify_message(
            provider=provider,
            model=model,
            from_email=message.from_email,
            from_name=message.from_name,
            subject=message.subject,
            body_text=message.body_text or message.preview,
            headers_text=None,
            attachment_names=[a.filename for a in atts],
            auth_results=message.auth_results,
            internal_domains=settings.internal_domain_list,
            recipients=[
                str(a.get("email")) for a in [*(message.to_addrs or []), *(message.cc_addrs or [])] if a.get("email")
            ],
            categories=categories,
        )
        if outcome.run_status is not None and outcome.model:
            db.add(
                AiRun(
                    purpose="eval",
                    provider=settings.llm_provider,
                    model=outcome.model,
                    input_tokens=outcome.input_tokens,
                    output_tokens=outcome.output_tokens,
                    cost_usd=outcome.ai_run_cost_usd,
                    latency_ms=outcome.latency_ms,
                    mailbox_id=message.mailbox_id,
                    message_id=message.id,
                    status=outcome.run_status,
                    error_class=outcome.error_class,
                )
            )
            spent += outcome.ai_run_cost_usd
            cost += outcome.ai_run_cost_usd
        result = outcome.result
        rows.append(
            EvalRow(lb.category, result.category if result else None, lb.language, result.language if result else None)
        )
    await db.flush()
    return rows, cost, skipped


async def save_summary(db: AsyncSession, report: EvalReport, *, mode: str, model: str | None) -> dict[str, Any]:
    """The last run for 17f — aggregates only."""
    summary = {
        **report.to_summary(),
        "mode": mode,
        "model": model,
        "gate": str(int(ACCURACY_GATE * 100)),
        "passed": report.passes(),
        "run_at": datetime.now(UTC).isoformat(),
    }
    await save_org_section(db, SECTION_EVAL, summary)
    return summary


async def score(
    db: AsyncSession,
    settings: Settings,
    labels: list[Label],
    *,
    live: bool = False,
    save: bool = False,
    provider: LLMProvider | None = None,
) -> tuple[EvalReport, str]:
    """Score labels (from the CLI or the 17f upload); `save` keeps the aggregates for 17f. The caller commits."""
    notes = ""
    if live:
        rows, cost, skipped = await _live(db, settings, provider or get_llm_provider(settings), labels)
        notes = f"\nlive cost: {cost:.4f} USD" + (f"; {skipped} skipped (daily budget used up)" if skipped else "")
    else:
        rows = await _stored(db, labels)
    report = evaluate(rows)
    mode = "live" if live else "stored"
    if save:
        await save_summary(db, report, mode=mode, model=(settings.llm_model_classify or None) if live else None)
    return report, format_report(report, mode=mode) + notes


async def run(
    db: AsyncSession,
    settings: Settings,
    csv_path: Path,
    *,
    live: bool = False,
    limit: int | None = None,
    save: bool = False,
    provider: LLMProvider | None = None,
) -> tuple[EvalReport, str]:
    labels = read_labels(csv_path, category_lookup(await load_category_data(db)))[: limit or None]
    result = await score(db, settings, labels, live=live, save=save, provider=provider)
    await db.commit()
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.ai.eval_cli", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sample = sub.add_parser("sample", help="write a label CSV of N random classified messages (server path)")
    p_sample.add_argument("--sample", type=int, default=SAMPLE_DEFAULT)
    p_sample.add_argument("--out", type=Path, required=True)
    p_run = sub.add_parser("run", help="score the AI against a labeled CSV")
    p_run.add_argument("--from-csv", type=Path, required=True)
    p_run.add_argument("--live", action="store_true", help="classify again with today's prompt (paid, budgeted)")
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--save", action="store_true", help="store the summary for Settings › 17f")
    return parser


async def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            if args.cmd == "sample":
                count = await sample(db, args.sample, args.out)
                print(f"wrote {count} rows to {args.out} (0600). Fill `category` on the server; never commit it.")
                return 0
            report, text = await run(db, settings, args.from_csv, live=args.live, limit=args.limit, save=args.save)
            print(text)
            return 0 if report.passes() else 1
    except EvalError as exc:
        print(f"eval: {exc}", file=sys.stderr)
        return 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
