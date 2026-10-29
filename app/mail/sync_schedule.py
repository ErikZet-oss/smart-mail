"""Schedule a mailbox sync from an API request instead of running it inside the request (#89)."""

from __future__ import annotations

import uuid

import structlog
from arq.connections import ArqRedis
from redis.asyncio import Redis

log = structlog.get_logger()

# Quick actions in a row (delete, delete, delete) end up as one sync: the job id is the poll's "all" id, and ARQ
# refuses a second job with the same id while one is queued or running (keep_result=0 frees it afterwards).
ACTION_SYNC_DELAY_S = 3


async def schedule_sync(redis: Redis, mailbox_id: uuid.UUID) -> bool:
    """Enqueue `sync_mailbox_job` (scope all) after a short delay. Never raises: the regular poll catches up."""
    try:
        arq = ArqRedis(connection_pool=redis.connection_pool)
        job = await arq.enqueue_job(
            "sync_mailbox_job",
            str(mailbox_id),
            "all",
            _job_id=f"mail-sync:{mailbox_id}:all",
            _defer_by=ACTION_SYNC_DELAY_S,
        )
    except Exception as exc:
        log.warning("mail.sync_schedule_failed", mailbox_id=str(mailbox_id), error=type(exc).__name__)
        return False
    return job is not None
