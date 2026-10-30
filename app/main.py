"""Smart Mail API."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app import __version__
from app.api import (
    ai_mail,
    auth,
    compose,
    compose_ai,
    contacts,
    mail,
    messages,
    notifications,
    persons,
    search,
    security_2fa,
    settings_ai,
    settings_autonomy,
    suggestions,
    system,
)
from app.api import settings as settings_api
from app.core import middleware
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

log = structlog.get_logger(__name__)

# Short, dedicated budget so /readyz never waits on a slow app request (pilot #18 B4).
CHECK_TIMEOUT_S = 1.5
READYZ_BUDGET_S = 2.0


async def _check_db(engine: AsyncEngine) -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # report, never crash the probe
        log.warning("readyz.db_failed", error=type(exc).__name__)
        return False


async def _check_redis(redis_url: str) -> bool:
    """Fresh short-timeout client — independent of the app Redis pool."""
    probe: Redis | None = None
    try:
        probe = Redis.from_url(
            redis_url,
            socket_connect_timeout=CHECK_TIMEOUT_S,
            socket_timeout=CHECK_TIMEOUT_S,
        )
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            return bool(await probe.ping())
    except Exception as exc:
        log.warning("readyz.redis_failed", error=type(exc).__name__)
        return False
    finally:
        if probe is not None:
            with contextlib.suppress(Exception):
                await probe.aclose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # pool_timeout keeps /readyz from waiting long when the pool is busy (pilot #18 B4).
        app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_timeout=2)
        app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        log.info("app.started", version=__version__, env=settings.app_env)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    # OpenAPI UI only in local development — never on test/prod VPS (CLAUDE.md §11).
    docs = "/api/docs" if settings.app_env == "dev" else None
    openapi = "/api/openapi.json" if settings.app_env == "dev" else None
    app = FastAPI(
        title="Smart Mail",
        version=__version__,
        lifespan=lifespan,
        docs_url=docs,
        openapi_url=openapi,
    )
    app.state.settings = settings
    middleware.install(app, settings)
    # Trust X-Forwarded-For from Docker-edge proxies (nginx ← Caddy / cloudflared). Same list as
    # FORWARDED_ALLOW_IPS for uvicorn --proxy-headers; required in tests (no uvicorn wrapper).
    if settings.forwarded_allow_ips.strip():
        from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.forwarded_allow_ips)
    app.include_router(auth.router)
    app.include_router(persons.router)
    app.include_router(security_2fa.router)
    app.include_router(mail.router)
    app.include_router(messages.router)
    app.include_router(ai_mail.router)
    app.include_router(suggestions.router)
    app.include_router(compose.router)
    app.include_router(compose_ai.router)
    app.include_router(settings_api.router)
    app.include_router(settings_ai.router)
    app.include_router(settings_autonomy.router)
    app.include_router(contacts.router)
    app.include_router(search.router)
    app.include_router(notifications.router)
    app.include_router(system.router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process runs. No dependencies are checked."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["system"])
    async def readyz(response: Response) -> dict[str, Any]:
        """Readiness: database and Redis reachable. Money and the AI provider are NOT required (CLAUDE.md §1).

        Own short budget — must not wait on other in-flight requests (pilot #18 B4).
        """
        try:
            async with asyncio.timeout(READYZ_BUDGET_S):
                db_ok, redis_ok = await asyncio.gather(
                    _check_db(app.state.engine),
                    _check_redis(settings.redis_url),
                )
        except TimeoutError:
            log.warning("readyz.budget_exceeded")
            db_ok, redis_ok = False, False
        ready = db_ok and redis_ok
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ready else "not_ready", "checks": {"database": db_ok, "redis": redis_ok}}

    @app.get("/api/version", tags=["system"])
    async def version() -> dict[str, str]:
        return {"version": __version__, "env": settings.app_env}

    return app


app = create_app()
