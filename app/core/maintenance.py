"""Maintenance mode (SCREENS_SPEC W17). While on, the API answers 503 `maintenance` and the web shows W17."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis.asyncio import Redis

KEY = "smartmail:maintenance"


async def get(redis: Redis) -> dict[str, Any] | None:
    raw = await redis.get(KEY)
    if raw is None:
        return None
    data: dict[str, Any] = json.loads(raw)
    return data


async def start(redis: Redis, until: datetime | None) -> None:
    await redis.set(KEY, json.dumps({"until": until.isoformat() if until else None}))


async def stop(redis: Redis) -> None:
    await redis.delete(KEY)
