"""Write endpoints of the bridge (Phase 3f: only the CRM activity after an approved send). HMAC + approval JWT."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from app.approval import verify_approval
from app.backend import MoneyBackend
from app.models import ActivityIn, ActivityOut, ArticleCreated, ArticleCreateIn, DeliveryNoteCreated, DeliveryNoteIn

# D32 (#239): the write routes that `MONEY_PROD_ALLOW` may open on PROD, by exact method + path
PROD_ALLOWABLE: dict[tuple[str, str], str] = {
    ("POST", "/articles"): "create_article",
    ("POST", "/delivery-notes/received"): "create_delivery_note",  # #247 D33: only as a koncept
}
# D33: a body that would finish (approve) the note is never accepted — Money must keep it as „Uložiť ako koncept“
APPROVAL_FIELDS = ("Schvalil_ID", "DatumSchvaleni")


async def refuse_on_prod(request: Request) -> None:
    """#212: one guard for the whole write router — on the PRODUCTION agenda every write answers 403 before the
    approval JWT is checked and before Money is called. New write routes inherit it. D32: the only exception is a route
    listed in `PROD_ALLOWABLE` whose action is also named in the bridge `.env` `MONEY_PROD_ALLOW` (default empty)."""
    settings = request.app.state.settings
    if not settings.read_only:
        return
    action = PROD_ALLOWABLE.get((request.method, request.url.path))
    if action is None or not settings.prod_allows(action):
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


@router.post("/articles")
async def create_article(request: Request, x_approval_token: str | None = Header(default=None)) -> ArticleCreated:
    """D32 / MONEY_API 5.5.8b `CreateArticle` after the user's click: single-use approval JWT bound to this exact body;
    the catalog is checked again right before the mutation (409 `catalog_exists`); never retried."""
    settings = request.app.state.settings
    body = await request.body()
    verify_approval(
        x_approval_token,
        public_key=settings.approval_jwt_public_key,
        action="article.create",
        body=body,
        jtis=request.app.state.jtis,
    )
    try:
        article = ArticleCreateIn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail={"code": "article_invalid"}) from None
    backend: MoneyBackend = request.app.state.backend
    return await backend.create_article(article)


def koncept_only(body: bytes) -> None:
    """D33: 422 `not_koncept` for a body without `Faze: 0` + `Schvaleno: false` or with approval fields — checked on
    the raw JSON before the model, so the refusal is explicit (also on the TEST agenda)."""
    try:
        data: Any = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "delivery_note_invalid"}) from None
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail={"code": "delivery_note_invalid"})
    faze, schvaleno = data.get("Faze"), data.get("Schvaleno")
    if type(faze) is not int or faze != 0 or schvaleno is not False or any(k in data for k in APPROVAL_FIELDS):
        raise HTTPException(status_code=422, detail={"code": "not_koncept"})


@router.post("/delivery-notes/received")
async def create_delivery_note(
    request: Request, x_approval_token: str | None = Header(default=None)
) -> DeliveryNoteCreated:
    """#247 / D33 / MONEY_API 5.5.7 `CreateReceivedDeliveryNote` as a koncept after the person's approval: single-use
    approval JWT bound to this exact body; own SMID → returned; same supplier + `Odkaz` → 409 `duplicate`; never
    retried (after a timeout the SMID is looked up once); read back."""
    settings = request.app.state.settings
    body = await request.body()
    verify_approval(
        x_approval_token,
        public_key=settings.approval_jwt_public_key,
        action="delivery_note.create",
        body=body,
        jtis=request.app.state.jtis,
    )
    koncept_only(body)
    try:
        note = DeliveryNoteIn.model_validate_json(body)
    except ValidationError:
        raise HTTPException(status_code=422, detail={"code": "delivery_note_invalid"}) from None
    backend: MoneyBackend = request.app.state.backend
    return await backend.create_delivery_note(note)
