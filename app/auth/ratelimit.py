"""Login rate limit per account and per IP (CLAUDE.md §11, SCREENS_SPEC W1: 5 wrong attempts lock for 5 minutes).

Every failed attempt — wrong IMAP password, unknown/disabled account, wrong 2FA code — counts and restarts the
lock window. "Mail server unavailable" does not count. A successful login clears the account counter.
"""

from __future__ import annotations

from dataclasses import dataclass

from redis.asyncio import Redis

from app.core.config import Settings

PREFIX = "smartmail:login:fail"


@dataclass(frozen=True)
class Lock:
    locked: bool
    retry_after_s: int = 0


class LoginRateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self.redis = redis
        self.window_s = settings.login_lock_minutes * 60
        self.max_account = settings.login_max_failures
        self.max_ip = settings.login_ip_max_failures

    @staticmethod
    def _keys(email: str, ip: str | None) -> tuple[str, str | None]:
        return f"{PREFIX}:acct:{email}", (f"{PREFIX}:ip:{ip}" if ip else None)

    async def check(self, email: str, ip: str | None) -> Lock:
        acct_key, ip_key = self._keys(email, ip)
        for key, limit in ((acct_key, self.max_account), (ip_key, self.max_ip)):
            if key is None:
                continue
            raw = await self.redis.get(key)
            if raw is not None and int(raw) >= limit:
                ttl = await self.redis.ttl(key)
                return Lock(True, max(int(ttl), 1))
        return Lock(False)

    async def fail(self, email: str, ip: str | None) -> None:
        acct_key, ip_key = self._keys(email, ip)
        pipe = self.redis.pipeline()
        for key in (acct_key, ip_key):
            if key is not None:
                pipe.incr(key)
                pipe.expire(key, self.window_s)
        await pipe.execute()

    async def success(self, email: str) -> None:
        acct_key, _ = self._keys(email, None)
        await self.redis.delete(acct_key)
