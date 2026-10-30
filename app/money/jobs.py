"""Money cache sync schedule (Settings 13e): delta every N minutes, nightly full, manual „Synchronizovať teraz“.

Runs only with FEATURE_MONEY=true. One run at a time (Redis lock), so the cron and a manual run never overlap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.ai.models import OrgSettings
from app.core.config import Settings
from app.money.bridge_client import BridgeClient
from app.money.cache_sync import DEFAULT_INTERVAL, ENTITIES, INTERVALS, SyncResult, due, needs_nightly_full, sync_entity
from app.money.models import MoneySyncState

SECTION_SYNC = "money.sync"
LOCK_KEY = "smartmail:money:sync-lock"
LOCK_TTL_S = 15 * 60
NIGHTLY_HOURS = (1, 2, 3, 4)  # UTC; a full run happens in this window once a day


async def sync_interval(db: AsyncSession) -> int:
    row = await db.scalar(select(OrgSettings).where(OrgSettings.section == SECTION_SYNC))
    value = (row.data if row else {}).get("interval_min")
    return value if value in INTERVALS else DEFAULT_INTERVAL


async def run_money_sync(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    redis: Redis,
    *,
    force: bool = False,
    client: BridgeClient | None = None,
    now: datetime | None = None,
) -> list[SyncResult]:
    """`force` = manual run: every entity now (companies as delta). Otherwise only what is due."""
    if not settings.feature_money:
        return []
    if not await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_S):
        return []
    now = now or datetime.now(UTC)
    results: list[SyncResult] = []
    own = client is None
    bridge = client or BridgeClient(settings)
    try:
        async with sessionmaker() as db:
            interval = await sync_interval(db)
            states: dict[str, Any] = {s.entity: s for s in (await db.scalars(select(MoneySyncState))).all()}
            for entity in ENTITIES:
                state = states.get(entity)
                nightly = now.hour in NIGHTLY_HOURS and needs_nightly_full(state, now)
                if entity == "codebooks":
                    run = force or needs_nightly_full(state, now)  # daily (MONEY_API §4)
                else:
                    run = force or nightly or due(state, interval, now)
                if not run:
                    continue
                results.append(await sync_entity(db, bridge, entity, full=nightly and entity == "companies"))
                await db.commit()
                if results[-1].status != "ok":
                    break  # Money is down: the next entities would fail the same way
    finally:
        await redis.delete(LOCK_KEY)
        if own:
            await bridge.aclose()
    return results
