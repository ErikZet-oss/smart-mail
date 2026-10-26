"""Smart Mail API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app import __version__
from app.api import auth, persons, system
from app.core import middleware
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

log = structlog.get_logger(__name__)

CHECK_TIMEOUT_S = 2.0


async def _check_db(engine: AsyncEngine) -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S), engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # report, never crash the probe
        log.warning("readyz.db_failed", error=type(exc).__name__)
        return False


async def _check_redis(redis: Redis) -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            return bool(await redis.ping())
    except Exception as exc:
        log.warning("readyz.redis_failed", error=type(exc).__name__)
        return False


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_async_engine(settings.database_url, pool_pre_ping=True)
        app.state.sessionmaker = async_sessionmaker(app.state.engine, expire_on_commit=False)
        app.state.redis = Redis.from_url(settings.redis_url)
        log.info("app.started", version=__version__, env=settings.app_env)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            await app.state.engine.dispose()

    app = FastAPI(
        title="Smart Mail",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    middleware.install(app, settings)
    app.include_router(auth.router)
    app.include_router(persons.router)
    app.include_router(system.router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        """Liveness: the process runs. No dependencies are checked."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["system"])
    async def readyz(response: Response) -> dict[str, Any]:
        """Readiness: database and Redis reachable. Money and the AI provider are NOT required (CLAUDE.md §1)."""
        db_ok, redis_ok = await asyncio.gather(_check_db(app.state.engine), _check_redis(app.state.redis))
        ready = db_ok and redis_ok
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ready else "not_ready", "checks": {"database": db_ok, "redis": redis_ok}}

    @app.get("/api/version", tags=["system"])
    async def version() -> dict[str, str]:
        return {"version": __version__, "env": settings.app_env}

    return app


app = create_app()
