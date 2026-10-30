"""2f `make eval`: server-side labels, scoring with a confusion table, the 17f summary — never mail text in reports."""

from __future__ import annotations

import csv
import stat
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.eval import SECTION_EVAL, EvalRow, evaluate, format_report
from app.ai.eval_cli import EvalError, read_labels, run, sample
from app.ai.models import AiRun, Classification, OrgSettings
from app.core.config import Settings
from app.mail.models import Message
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response, _seed_ai_mailbox
from tests.test_knowledge_2e import _admin


def test_2f_eval_scores_accuracy_precision_recall_and_confusions() -> None:
    rows = [
        EvalRow("inquiry", "inquiry", "sk", "sk"),
        EvalRow("inquiry", "order", "sk", "sk"),
        EvalRow("order", "order", "cs", "sk"),
        EvalRow("supplier_document", "invoice_request"),
        EvalRow("payment", None),
    ]
    report = evaluate(rows)
    assert report.total == 5 and report.correct == 2 and report.unclassified == 1
    assert report.accuracy == Decimal("0.4") and not report.passes()
    assert report.language_accuracy == Decimal(2) / Decimal(3)
    summary = report.to_summary()
    assert summary["accuracy"] == "40.0" and summary["too_small"] is True
    assert summary["per_category"]["order"] == {
        "support": 1,
        "predicted": 2,
        "correct": 1,
        "precision": "50.0",
        "recall": "100.0",
    }
    confusions = {(c["label"], c["predicted"]): c["count"] for c in summary["confusion"]}
    assert confusions == {
        ("inquiry", "order"): 1,
        ("supplier_document", "invoice_request"): 1,
        ("payment", "(none)"): 1,
    }
    text = format_report(report, mode="stored")
    assert "FAIL" in text and "supplier_document → invoice_request: 1" in text


def test_2f_eval_gate_is_90_percent() -> None:
    assert evaluate([EvalRow("a", "a")] * 9 + [EvalRow("a", "b")]).passes()
    assert not evaluate([EvalRow("a", "a")] * 8 + [EvalRow("a", "b")] * 2).passes()


def test_2f_label_csv_never_inside_the_repo(tmp_path: Path) -> None:
    repo_file = Path(__file__).resolve().parents[1] / "eval_labels.csv"
    with pytest.raises(EvalError, match="inside the repository"):
        import asyncio

        asyncio.run(sample(None, 1, repo_file))  # type: ignore[arg-type]
    assert not repo_file.exists()


def _write_labels(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["message_uuid", "subject", "predicted", "category", "language"])
        writer.writeheader()
        writer.writerows(rows)


def test_2f_read_labels_skips_empty_and_rejects_typos(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    _write_labels(
        path,
        [
            {"message_uuid": "00000000-0000-0000-0000-000000000001", "category": "inquiry", "language": "sk"},
            {"message_uuid": "00000000-0000-0000-0000-000000000002", "category": ""},
        ],
    )
    assert len(read_labels(path, {"inquiry"})) == 1
    _write_labels(path, [{"message_uuid": "00000000-0000-0000-0000-000000000001", "category": "inqiury"}])
    with pytest.raises(EvalError, match="unknown category"):
        read_labels(path, {"inquiry"})


async def _classified(db: AsyncSession, categories: list[str]) -> list[Message]:
    mailbox = await _seed_ai_mailbox(db, n_messages=len(categories))
    messages = list((await db.scalars(select(Message).where(Message.mailbox_id == mailbox.id))).all())
    for i, (message, category) in enumerate(zip(messages, categories, strict=True)):
        db.add(
            Classification(
                mailbox_id=mailbox.id,
                message_id=message.id,
                message_id_header=f"eval-{i}@x",
                category=category,
                language="sk",
                status="done",
                payload={},
            )
        )
    await db.flush()
    return messages


async def test_2f_sample_writes_0600_csv_without_bodies(db: AsyncSession, tmp_path: Path) -> None:
    await _classified(db, ["inquiry", "order"])
    out = tmp_path / "eval" / "labels.csv"
    assert await sample(db, 10, out) == 2
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    text = out.read_text(encoding="utf-8")
    assert "Prosím o cenu M8" not in text  # the body never goes into the CSV
    with out.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["predicted"] for r in rows} == {"inquiry", "order"} and all(r["category"] == "" for r in rows)
    with pytest.raises(EvalError, match="overwrite"):
        await sample(db, 1, out)


async def test_2f_run_stored_saves_aggregates_for_17f(db: AsyncSession, settings: Settings, tmp_path: Path) -> None:
    messages = await _classified(db, ["inquiry", "order", "order"])
    path = tmp_path / "labels.csv"
    _write_labels(
        path,
        [
            {"message_uuid": str(messages[0].id), "subject": "tajný predmet", "category": "inquiry"},
            {"message_uuid": str(messages[1].id), "category": "order"},
            {"message_uuid": str(messages[2].id), "category": "complaint"},
        ],
    )
    report, text = await run(db, settings, path, save=True)
    assert report.total == 3 and report.correct == 2 and "complaint → order: 1" in text
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_EVAL))
    assert row is not None and row.data["mode"] == "stored" and row.data["passed"] is False
    assert "tajný" not in str(row.data) and str(messages[0].id) not in str(row.data)  # aggregates only


async def test_2f_run_live_classifies_again_and_records_eval_cost(
    db: AsyncSession, settings: Settings, tmp_path: Path
) -> None:
    messages = await _classified(db, ["other"])
    path = tmp_path / "labels.csv"
    _write_labels(path, [{"message_uuid": str(messages[0].id), "category": "inquiry"}])
    llm = ScriptedAnthropic([_ok_response()])  # the model answers inquiry
    live = settings.model_copy(
        update={"anthropic_api_key": SecretStr("sk-test"), "llm_model_classify": "claude-haiku-4-5-20251001"}
    )
    report, text = await run(db, live, path, live=True, provider=llm)
    assert report.correct == 1 and "live cost" in text and len(llm.calls) == 1
    eval_run = await db.scalar(select(AiRun).where(AiRun.purpose == "eval"))
    assert eval_run is not None and eval_run.cost_usd > 0
    stored = await db.scalar(select(Classification).where(Classification.message_id == messages[0].id))
    assert stored is not None and stored.category == "other"  # eval never rewrites stored classifications


async def test_2f_usage_shows_last_eval(client: Client, db: AsyncSession, mail_server: FakeMailServer) -> None:
    await _admin(client, db, mail_server)
    assert (await client.get("/api/settings/ai/usage")).json()["eval"] is None
    summary = evaluate([EvalRow("inquiry", "order")] + [EvalRow("order", "order")] * 9).to_summary()
    db.add(
        OrgSettings(
            section=SECTION_EVAL,
            data={
                **summary,
                "mode": "live",
                "model": "m",
                "gate": "90",
                "passed": True,
                "run_at": "2026-10-30T10:00:00Z",
            },
        )
    )
    await db.commit()
    out = (await client.get("/api/settings/ai/usage")).json()["eval"]
    assert out["accuracy"] == "90.0" and out["passed"] is True
    assert out["confusion"] == [{"label": "inquiry", "predicted": "order", "count": 1}]
