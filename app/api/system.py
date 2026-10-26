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
async def system_info(request: Request) -> dict[str, str | None]:
    """Public, no session needed: W16a shows "Požiadať správcu" as a mailto to this address."""
    return {"admin_contact_email": request.app.state.settings.admin_contact_email}
