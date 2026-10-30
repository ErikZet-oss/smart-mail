"""#135: a cron retries AI work without waiting for new mail — only when there is work, never past 3 failures."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.catchup import has_pending_classify, has_pending_reply, mailboxes_with_work
from app.ai.models import AiRun, Classification
from app.workers.worker import ai_catchup
from tests.test_ai_reply_2c import MODEL, _seed


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, args, kwargs))


class _Maker:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def __call__(self) -> _Maker:
        return self

    async def __aenter__(self) -> AsyncSession:
        return self.db

    async def __aexit__(self, *_exc: object) -> None:
        return None


async def test_135_cron_enqueues_job_when_a_reply_draft_is_missing(db: AsyncSession) -> None:
    mailbox, _message = await _seed(db)  # classified inquiry-like mail, needs_reply, no suggestion yet
    arq = FakeArq()
    assert await ai_catchup({"sessionmaker": _Maker(db), "redis": arq}) == 1
    assert arq.jobs == [("process_mailbox_ai_job", (str(mailbox.id),), {"_job_id": f"mail-ai:{mailbox.id}"})]


async def test_135_nothing_to_do_or_ai_off_means_no_job(db: AsyncSession) -> None:
    mailbox, _message = await _seed(db, needs_reply=False)
    assert not await has_pending_reply(db, mailbox) and not await has_pending_classify(db, mailbox)
    assert await mailboxes_with_work(db) == []
    mailbox2, _ = await _seed(db)
    mailbox2.ai_enabled = False
    await db.flush()
    assert await mailboxes_with_work(db) == []


async def test_135_three_failed_drafts_stop_the_retries(db: AsyncSession) -> None:
    mailbox, message = await _seed(db)
    for _ in range(2):
        db.add(AiRun(purpose="draft", provider="anthropic", model=MODEL, status="error", message_id=message.id))
    await db.flush()
    assert await has_pending_reply(db, mailbox)  # 2 failures: still retried
    db.add(AiRun(purpose="draft", provider="anthropic", model=MODEL, status="invalid_output", message_id=message.id))
    await db.flush()
    assert not await has_pending_reply(db, mailbox)  # 3rd failure: given up, the budget is safe


async def test_135_unclassified_mail_is_pending_until_three_attempts(db: AsyncSession) -> None:
    mailbox, message = await _seed(db)
    await db.execute(delete(Classification).where(Classification.message_id == message.id))
    await db.flush()
    assert await has_pending_classify(db, mailbox)  # never classified (e.g. the provider failed)
    db.add(Classification(mailbox_id=mailbox.id, message_id=message.id, status="pending", payload={"llm_attempts": 2}))
    await db.flush()
    assert await has_pending_classify(db, mailbox)
    cls = await db.scalar(select(Classification).where(Classification.message_id == message.id))
    assert cls is not None
    cls.payload = {"llm_attempts": 3}
    await db.flush()
    assert not await has_pending_classify(db, mailbox)
