"""System endpoints used by the system screens (SCREENS_SPEC W16a, W17)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core import maintenance

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/maintenance")
async def maintenance_state(request: Request) -> dict[str, Any]:
    state = await maintenance.get(request.app.state.redis)
    return {"active": state is not None, "until": state.get("until") if state else None}


@router.get("/info")
async def system_info(request: Request) -> dict[str, object]:
    """Public, no session needed: W16a admin mailto + feature flags for the SPA."""
    settings = request.app.state.settings
    return {
        "admin_contact_email": settings.admin_contact_email,
        "features": {"money": settings.feature_money},
    }
