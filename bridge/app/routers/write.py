"""Write endpoints of the bridge (Phase 3f: only the CRM activity after an approved send). HMAC + approval JWT."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from app.approval import verify_approval
from app.backend import MoneyBackend
from app.models import ActivityIn, ActivityOut


async def refuse_on_prod(request: Request) -> None:
    """#212: one guard for the whole write router — on the PRODUCTION agenda every write answers 403 before the
    approval JWT is checked and before Money is called. New write routes inherit it."""
    if request.app.state.settings.read_only:
        raise HTTPException(status_code=403, detail={"code": "prod_read_only"})


router = APIRouter(dependencies=[Depends(refuse_on_prod)])


@router.post("/activities")
async def create_activity(request: Request, x_approval_token: str | None = Header(default=None)) -> ActivityOut:
    settings = request.app.state.settings
    body = await request.body()
    claims = verify_approval(
        x_approval_token,
        public_key=settings.approval_jwt_public_key,
        action="activity.create",
        body=body,
        jtis=request.app.state.jtis,
    )
    try:
        activity = ActivityIn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail={"code": "activity_invalid"}) from None
    if str(claims.get("company_id")) != str(activity.company_id):
        raise HTTPException(status_code=403, detail={"code": "approval_wrong_company"})
    backend: MoneyBackend = request.app.state.backend
    return await backend.create_activity(activity)
