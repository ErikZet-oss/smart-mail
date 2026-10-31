"""Money S4 bridge — the only service with Money credentials (MONEY_API §6). Phase 3: read-only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from app.approval import JtiCache
from app.auth import ReplayCache, verify_request
from app.backend import MoneyBackend, MoneyError, MoneyUnavailable, WaitingForProbe
from app.config import BridgeSettings, get_settings
from app.filters import UnsafeFilterValue
from app.models import Health
from app.routers import read, write

__version__ = "0.3.0"


def make_backend(settings: BridgeSettings) -> MoneyBackend:
    if settings.money_backend == "api":
        from app.api_backend import ApiBackend

        return ApiBackend(settings)
    from app.mock import MockBackend

    return MockBackend()


def create_app(settings: BridgeSettings | None = None, backend: MoneyBackend | None = None) -> FastAPI:
    settings = settings or get_settings()
    problem = settings.startup_problem()
    if problem is not None and backend is None:
        raise RuntimeError(problem)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.backend.aclose()

    app = FastAPI(
        title="Smart Mail – Money bridge", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )
    app.state.backend = backend or make_backend(settings)
    app.state.settings = settings
    app.state.jtis = JtiCache()
    replay = ReplayCache()

    async def hmac_guard(request: Request) -> None:
        await verify_request(
            request,
            key_id=settings.bridge_hmac_key_id,
            secret=settings.bridge_hmac_secret.get_secret_value(),
            replay=replay,
        )

    @app.exception_handler(MoneyUnavailable)
    async def _unavailable(_: Request, exc: MoneyUnavailable) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": {"code": "money_unavailable"}})

    @app.exception_handler(MoneyError)
    async def _money_error(_: Request, exc: MoneyError) -> JSONResponse:
        return JSONResponse(status_code=502, content={"detail": {"code": "money_error"}})

    @app.exception_handler(WaitingForProbe)
    async def _probe(_: Request, exc: WaitingForProbe) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": {"code": "waiting_for_probe", "what": exc.what}})

    @app.exception_handler(UnsafeFilterValue)
    async def _unsafe(_: Request, exc: UnsafeFilterValue) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": {"code": "unsafe_filter_value", "field": exc.field}})

    @app.get("/healthz")
    async def healthz() -> Health:
        return Health(
            status="ok",
            version=__version__,
            backend=settings.money_backend,
            agenda=settings.money_agenda_label,
            writes_enabled=settings.writes_enabled,
        )

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, str]:
        """Token + `Version` on the real API; the mock is always ready."""
        try:
            version = await app.state.backend.version()
        except (MoneyUnavailable, MoneyError):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "reason": "money_unavailable"}
        return {"status": "ready", "backend": settings.money_backend, "money_version": version}

    app.include_router(read.router, dependencies=[Depends(hmac_guard)])
    app.include_router(write.router, dependencies=[Depends(hmac_guard)])
    return app


app = create_app()
