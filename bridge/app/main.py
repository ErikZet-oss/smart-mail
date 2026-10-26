"""Money S4 bridge (Phase 0: health only, mock backend by default)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Response, status

from app.config import BridgeSettings, get_settings

__version__ = "0.1.0"


def create_app(settings: BridgeSettings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Smart Mail – Money bridge", version=__version__)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "backend": settings.money_backend,
            "agenda": settings.money_agenda_label,
            "writes_enabled": settings.writes_enabled,
        }

    @app.get("/readyz")
    async def readyz(response: Response) -> dict[str, Any]:
        """Mock is always ready. The real Money check (token + one cheap query) is added in Phase 3."""
        if settings.money_backend == "api" and not (settings.money_base_url and settings.money_client_id):
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "not_ready", "reason": "MONEY_BASE_URL / MONEY_CLIENT_ID missing"}
        return {"status": "ready", "backend": settings.money_backend}

    return app


app = create_app()
