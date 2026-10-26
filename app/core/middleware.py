"""HTTP middleware: security headers, CSRF, maintenance mode, unexpected errors (CLAUDE.md §11)."""

from __future__ import annotations

import secrets

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.auth.security import csrf_valid
from app.core import maintenance
from app.core.config import Settings

log = structlog.get_logger(__name__)

SESSION_COOKIE = "sm_session"
CSRF_COOKIE = "sm_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# reachable during maintenance so that W17 can show the expected end and health checks keep working
MAINTENANCE_OPEN = frozenset({"/api/version", "/api/system/maintenance", "/healthz", "/readyz"})


def error(status: int, code: str, **extra: object) -> JSONResponse:
    return JSONResponse({"detail": {"code": code, **extra}}, status_code=status)


def install(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            response.headers.setdefault("Cache-Control", "no-store")
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    class Guard(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
            path = request.url.path
            if path.startswith("/api/") and path not in MAINTENANCE_OPEN:
                try:
                    state = await maintenance.get(request.app.state.redis)
                except Exception as exc:  # Redis down must not take the whole API with it
                    log.warning("maintenance.check_failed", error=type(exc).__name__)
                    state = None
                if state is not None:
                    return error(503, "maintenance", until=state.get("until"))
            if path.startswith("/api/") and request.method not in SAFE_METHODS:
                header = request.headers.get(CSRF_HEADER, "")
                cookie = request.cookies.get(CSRF_COOKIE, "")
                if (
                    not header
                    or not secrets.compare_digest(header.encode(), cookie.encode())
                    or not csrf_valid(settings, header, request.cookies.get(SESSION_COOKIE))
                ):
                    return error(403, "csrf")
            try:
                return await call_next(request)
            except Exception:
                ref = secrets.token_hex(4).upper()
                log.exception("request.failed", ref=ref, path=path, method=request.method)
                return error(500, "server_error", ref=ref)

    app.add_middleware(Guard)
