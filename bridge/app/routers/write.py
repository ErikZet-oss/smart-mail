"""Write endpoints of the bridge (Phase 3f: only the CRM activity after an approved send). HMAC + approval JWT."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import ValidationError

from app.approval import verify_approval
from app.backend import MoneyBackend
from app.models import ActivityIn, ActivityOut, ArticleCreated, ArticleCreateIn

# D32 (#239): the write routes that `MONEY_PROD_ALLOW` may open on PROD, by exact method + path
PROD_ALLOWABLE: dict[tuple[str, str], str] = {("POST", "/articles"): "create_article"}


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
