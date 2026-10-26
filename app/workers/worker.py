"""ARQ worker (CLAUDE.md §2). Phase 0: a heartbeat cron proves the worker runs; jobs come in later phases.

Run: arq app.workers.worker.WorkerSettings
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

import structlog
from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging

log = structlog.get_logger(__name__)
HEARTBEAT_KEY = "smartmail:worker:heartbeat"


async def heartbeat(ctx: dict[str, Any]) -> str:
    now = datetime.now(UTC).isoformat()
    await ctx["redis"].set(HEARTBEAT_KEY, now, ex=300)
    return now


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    log.info("worker.started")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    functions: ClassVar[list[Any]] = [heartbeat]
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, minute=set(range(60)), run_at_startup=True)]
    on_startup = startup
