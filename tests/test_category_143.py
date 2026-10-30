"""#143 „Zmeniť kategóriu“ (a person's correction wins) and „Znova zaradiť (AI)“ (one budgeted classify call)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.eval import evaluate
from app.ai.eval_cli import correction_rows
from app.ai.models import AiRun, Classification
from app.auth.models import Role
from app.core.audit import AuditLog
from app.core.config import Settings
from app.mail.models import FolderMeta, Mailbox, Message
from tests.conftest import Client, FakeMailServer
from tests.test_ai_classify_review_2b import ScriptedAnthropic, _ok_response
from tests.test_mail_sync_1c import _signed_in

MODEL = "claude-haiku-4-5-20251001"


async def _mail(
    client: Client,
    db: AsyncSession,
    mail_server: FakeMailServer,
    role: Role = Role.sales,
    category: str = "invoice_request",
) -> tuple[Mailbox, Message]:
    mailbox = await _signed_in(client, db, mail_server, role=role)
    inbox = await db.scalar(select(FolderMeta).where(FolderMeta.mailbox_id == mailbox.id, FolderMeta.name == "INBOX"))
    assert inbox is not None
    message = Message(
        mailbox_id=mailbox.id,
        folder_id=inbox.id,
        uid=42,
        message_id="<fa-2026-0815@fixtech.example>",
        subject="Faktúra 2026/0815",
        from_email="faktury@fixtech.example",
        body_text="V prílohe posielame faktúru.",
    )
    db.add(message)
    await db.flush()
    db.add(
        Classification(
            mailbox_id=mailbox.id,
            message_id=message.id,
            message_id_header="fa-2026-0815@fixtech.example",
            category=category,
            status="done",
            payload={"needs_reply": True},
        )
    )
    await db.commit()
    return mailbox, message


def _url(message: Message, action: str) -> str:
    return f"/api/mail/mailboxes/default/messages/{message.id}/{action}"


async def test_143_correction_moves_the_view_and_is_audited(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, message = await _mail(client, db, mail_server)
    r = await client.send_json("POST", _url(message, "category"), {"category": "supplier_document"})
    assert r.status_code == 200 and r.json()["category"] == "supplier_document" and r.json()["corrected"] is True
    cls = await db.scalar(
        select(Classification).where(Classification.message_id == message.id).execution_options(populate_existing=True)
    )
    assert cls is not None and cls.category == "supplier_document"
    assert cls.payload["corrected_from"] == "invoice_request" and cls.payload["corrected_by_person_id"]
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "ai.category_corrected"))
    assert entry is not None and entry.details == {"before": "invoice_request", "after": "supplier_document"}
    # a second correction keeps the AI's original answer as the eval pair
    await client.send_json("POST", _url(message, "category"), {"category": "payment"})
    await db.refresh(cls)
    assert cls.payload["corrected_from"] == "invoice_request" and cls.category == "payment"
    report = evaluate(await correction_rows(db))
    assert report.total == 1 and report.correct == 0


async def test_143_only_enabled_categories_and_roles(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, message = await _mail(client, db, mail_server)
    r = await client.send_json("POST", _url(message, "category"), {"category": "nonsense"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "category_unknown"


@pytest.mark.parametrize(("role", "code"), [(Role.viewer, "read_only"), (Role.warehouse, "role_not_allowed")])
async def test_143_viewer_and_warehouse_cannot_change(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, role: Role, code: str
) -> None:
    _, message = await _mail(client, db, mail_server, role=role)
    r = await client.send_json("POST", _url(message, "category"), {"category": "supplier_document"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == code


async def test_143_reclassify_writes_a_new_result_and_ai_run(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    from app.ai.reclassify import reclassify

    mailbox, message = await _mail(client, db, mail_server)
    tool = {**(_ok_response().tool_input or {}), "category": "supplier_document", "needs_reply": False}
    llm = ScriptedAnthropic([_ok_response(tool_input=tool)])
    live = settings.model_copy(update={"anthropic_api_key": SecretStr("sk"), "llm_model_classify": MODEL})
    cls = await reclassify(db, mailbox, message, live, person_id=None, account_id=None, provider=llm)
    await db.commit()
    assert cls.category == "supplier_document" and cls.payload["needs_reply"] is False
    assert cls.payload["source"] == "reclassify" and len(llm.calls) == 1
    run = await db.scalar(select(AiRun).where(AiRun.message_id == message.id))
    assert run is not None and run.purpose == "classify" and run.cost_usd > 0
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "ai.reclassified")) is not None


async def test_143_reclassify_never_overwrites_a_correction_and_respects_budget(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, settings: Settings
) -> None:
    from app.ai.reclassify import ReclassifyError, reclassify

    mailbox, message = await _mail(client, db, mail_server)
    live = settings.model_copy(update={"anthropic_api_key": SecretStr("sk"), "llm_model_classify": MODEL})
    llm = ScriptedAnthropic([_ok_response()])
    # budget: 5 USD already spent today with a 1 USD budget → 429
    db.add(AiRun(purpose="classify", provider="anthropic", model="m", cost_usd=Decimal("5"), status="ok"))
    await db.commit()
    with pytest.raises(ReclassifyError) as err:
        await reclassify(
            db,
            mailbox,
            message,
            live.model_copy(update={"ai_daily_budget_usd": 1.0}),
            person_id=None,
            account_id=None,
            provider=llm,
        )
    assert err.value.code == "ai_budget_exceeded" and err.value.status == 429 and llm.calls == []

    r = await client.send_json("POST", _url(message, "category"), {"category": "supplier_document"})
    assert r.status_code == 200
    with pytest.raises(ReclassifyError) as err:
        await reclassify(db, mailbox, message, live, person_id=None, account_id=None, provider=llm)
    assert err.value.code == "category_corrected_manually" and llm.calls == []


async def test_143_reclassify_endpoint_answers_409_for_a_correction(
    client: Client, db: AsyncSession, mail_server: FakeMailServer
) -> None:
    _, message = await _mail(client, db, mail_server)
    await client.send_json("POST", _url(message, "category"), {"category": "supplier_document"})
    r = await client.send_json("POST", _url(message, "reclassify"), {})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "category_corrected_manually"


async def test_143_bulk_reclassify_enqueues_one_job_max_50(
    client: Client, db: AsyncSession, mail_server: FakeMailServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    jobs: list[tuple[Any, ...]] = []

    async def enqueue(self: Any, name: str, *args: Any, **kwargs: Any) -> None:
        jobs.append((name, *args))

    monkeypatch.setattr("arq.connections.ArqRedis.enqueue_job", enqueue)
    _, message = await _mail(client, db, mail_server)
    r = await client.send_json("POST", "/api/mail/mailboxes/default/ai/reclassify", {"message_ids": [str(message.id)]})
    assert r.status_code == 202 and r.json() == {"queued": 1}
    assert jobs and jobs[0][0] == "reclassify_messages_job" and jobs[0][2] == [str(message.id)]
    too_many = {"message_ids": [str(message.id)] * 51}
    assert (await client.send_json("POST", "/api/mail/mailboxes/default/ai/reclassify", too_many)).status_code == 422
