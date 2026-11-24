"""The main app's only way to Money: HMAC-signed GETs to the bridge (MONEY_API §6, signature as `bridge/app/auth.py`).

Money or the bridge being down must never break mail: every failure becomes `BridgeUnavailable`, and after
`FAILS_TO_OPEN` failures in a row the circuit stays open for `OPEN_SECONDS` (calls fail fast, the UI shows
„Money nedostupné“).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import date, datetime
from typing import Any, TypeVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.money.schemas import (
    Activity,
    ActivityOut,
    Article,
    ArticleCatalogInfo,
    ArticleCreated,
    CatalogFree,
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    DeliveryNoteCreated,
    DeliveryNoteTemplate,
    DeliverySearch,
    Health,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    OverduePage,
    PersonPage,
    ReceivedNoteRow,
    SupplierCode,
    SupplierCodePage,
)

TIMEOUT = httpx.Timeout(15.0, connect=3.0)
FAILS_TO_OPEN = 3
OPEN_SECONDS = 60.0
M = TypeVar("M", bound=BaseModel)


class BridgeUnavailable(Exception):
    def __init__(self, code: str = "money_unavailable") -> None:
        super().__init__(code)
        self.code = code


class BridgeRefused(Exception):
    """The bridge refused a write with 4xx (409 `catalog_exists`, 403 `prod_read_only` …) — Money was not changed."""

    def __init__(self, status: int, code: str, detail: dict[str, Any]) -> None:
        super().__init__(code)
        self.status, self.code, self.detail = status, code, detail


def sign(secret: str, method: str, path_qs: str, timestamp: str, body: bytes = b"") -> str:
    """Must stay byte-identical to `bridge/app/auth.py` (test vector in tests/test_money_bridge_client_3b.py)."""
    canonical = "\n".join([method.upper(), path_qs, timestamp, hashlib.sha256(body).hexdigest()]).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


def access_headers(settings: Settings) -> dict[str, str]:
    """Cloudflare Access service token for the tunnel to the office server (ADR-016); empty in dev and on the mock."""
    if settings.bridge_cf_access_client_id and settings.bridge_cf_access_client_secret:
        return {
            "CF-Access-Client-Id": settings.bridge_cf_access_client_id,
            "CF-Access-Client-Secret": settings.bridge_cf_access_client_secret.get_secret_value(),
        }
    return {}


class _Circuit:
    def __init__(self) -> None:
        self.fails = 0
        self.open_until = 0.0

    def check(self) -> None:
        if time.monotonic() < self.open_until:
            raise BridgeUnavailable("money_circuit_open")

    def success(self) -> None:
        self.fails = 0
        self.open_until = 0.0

    def failure(self) -> None:
        self.fails += 1
        if self.fails >= FAILS_TO_OPEN:
            self.open_until = time.monotonic() + OPEN_SECONDS


_circuit = _Circuit()  # per process: the API and the worker each keep their own


class BridgeClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._base = settings.bridge_url.rstrip("/")
        self._key_id = settings.bridge_hmac_key_id
        self._secret = settings.bridge_hmac_secret.get_secret_value()
        self._own = http is None
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT, headers=access_headers(settings))

    async def aclose(self) -> None:
        if self._own:
            await self._http.aclose()

    async def __aenter__(self) -> BridgeClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, *, signed: bool = True, allow_404: bool = False
    ) -> Any:
        _circuit.check()
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
        path_qs = f"{path}?{query}" if query else path
        headers: dict[str, str] = {}
        if signed:
            stamp = str(int(time.time()))
            headers = {
                "X-Bridge-Key-Id": self._key_id,
                "X-Bridge-Timestamp": stamp,
                "X-Bridge-Signature": sign(self._secret, "GET", path_qs, stamp),
            }
        try:
            resp = await self._http.get(self._base + path_qs, headers=headers)
        except httpx.HTTPError as exc:
            _circuit.failure()
            raise BridgeUnavailable() from exc
        if resp.status_code == 501:  # the bridge knows the call but waits for the probe report — not an outage
            raise BridgeUnavailable("waiting_for_probe")
        if resp.status_code >= 500 or resp.status_code in (401, 403):
            _circuit.failure()
            code = "money_unavailable"
            try:
                code = str(resp.json()["detail"]["code"])
            except (ValueError, KeyError, TypeError):
                pass
            raise BridgeUnavailable(code)
        _circuit.success()
        if resp.status_code == 404 and allow_404:
            return None
        if resp.status_code != 200:
            raise BridgeUnavailable(f"bridge_{resp.status_code}")
        return resp.json()

    async def _model(self, model: type[M], path: str, params: dict[str, Any] | None = None) -> M:
        data = await self._get(path, params)
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def health(self) -> Health:
        data = await self._get("/healthz", signed=False)
        try:
            return Health.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def ready(self) -> dict[str, str]:
        """`/readyz` touches Money itself (token + Version); 503 → `BridgeUnavailable`."""
        data = await self._get("/readyz", signed=False)
        return {str(k): str(v) for k, v in data.items()}

    async def companies(self, since: datetime | None, start: int, count: int) -> CompanyPage:
        params = {"since": since.isoformat() if since else None, "from": start, "count": count}
        return await self._model(CompanyPage, "/sync/companies", params)

    async def persons(self, since: datetime | None, start: int, count: int) -> PersonPage:
        params = {"since": since.isoformat() if since else None, "from": start, "count": count}
        return await self._model(PersonPage, "/sync/persons", params)

    async def _list(self, model: type[M], path: str, params: dict[str, Any] | None = None) -> list[M]:
        data = await self._get(path, params)
        try:
            return [model.model_validate(row) for row in data]
        except (ValidationError, TypeError) as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def company(self, money_id: uuid.UUID) -> Company | None:
        data = await self._get(f"/companies/{money_id}", allow_404=True)
        if data is None:
            return None
        try:
            return Company.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def receivables(self, money_id: uuid.UUID) -> list[IssuedInvoice]:
        return await self._list(IssuedInvoice, f"/companies/{money_id}/receivables")

    async def orders(self, money_id: uuid.UUID, since: date) -> list[Order]:
        return await self._list(Order, f"/companies/{money_id}/orders", {"since": since.isoformat()})

    async def deliveries(self, money_id: uuid.UUID, since: date) -> list[Delivery]:
        return await self._list(Delivery, f"/companies/{money_id}/deliveries", {"since": since.isoformat()})

    async def activities(self, money_id: uuid.UUID) -> list[Activity]:
        return await self._list(Activity, f"/companies/{money_id}/activities")

    # ----- Phase 4b (read-only): item matching -----

    async def search_articles(
        self, *, code: str | None = None, ean: str | None = None, q: str | None = None, limit: int | None = None
    ) -> list[Article]:
        """A value with `~ # | ( )` answers 422 in the bridge → `bridge_422` (never a broken filter). `limit` (≤ 100)
        only for the W6h Katalóg text search — an old bridge ignores it."""
        params: dict[str, Any] = {"code": code, "ean": ean, "q": q}
        if limit is not None:
            params["limit"] = limit
        return await self._list(Article, "/articles/search", params)

    async def article_variants(self, parent_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[Article]]:
        """#233 variants of up to 10 main cards (`NadrazenyArtikl_ID`) in one bridge call."""
        if not parent_ids:
            return {}
        data = await self._get("/articles/variants", {"parent_id": [str(p) for p in parent_ids[:10]]})
        try:
            return {uuid.UUID(k): [Article.model_validate(a) for a in v] for k, v in (data or {}).items()}
        except (ValidationError, ValueError, TypeError, AttributeError) as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def catalog_info(self, article_ids: list[uuid.UUID]) -> list[ArticleCatalogInfo]:
        """W6h Katalóg: e-shop flag + stock per warehouse of up to 100 articles (read only)."""
        if not article_ids:
            return []
        return await self._list(
            ArticleCatalogInfo, "/articles/catalog-info", {"id": [str(a) for a in article_ids[:100]]}
        )

    async def article(self, article_id: uuid.UUID) -> Article | None:
        data = await self._get(f"/articles/{article_id}", allow_404=True)
        if data is None:
            return None
        try:
            return Article.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def all_supplier_codes(self, since: datetime | None, start: int, count: int) -> SupplierCodePage:
        """#228 read cache sync: every `ArticleSuppliers` row (all suppliers), `ChangeFrom` delta, paged."""
        params = {"since": since.isoformat() if since else None, "from": start, "count": count}
        return await self._model(SupplierCodePage, "/sync/article-suppliers", params)

    async def lookup_supplier_code(self, supplier_id: uuid.UUID, code: str) -> list[SupplierCode]:
        """#228 one code exactly as written on the document (`Firma_ID` + `DodavatelskyKod` eq) — the fallback for a
        code the cache does not know yet. A value with `~ # | ( )` answers 422 there → `bridge_422`."""
        return await self._list(SupplierCode, f"/suppliers/{supplier_id}/article-codes/lookup", {"code": code})

    async def overdue(self, before: date, start: int, count: int) -> OverduePage:
        params = {"before": before.isoformat(), "from": start, "count": count}
        return await self._model(OverduePage, "/receivables/overdue", params)

    async def search_invoices(
        self,
        *,
        number: str | None = None,
        vs: str | None = None,
        company_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        order: str | None = None,
    ) -> InvoiceSearch:
        """MONEY_API §5.1 cascade in the bridge. A value with `~ # | ( )` answers 422 there → `bridge_422`."""
        params = {
            "number": number,
            "vs": vs,
            "order": order,
            "company_id": str(company_id) if company_id else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        }
        return await self._model(InvoiceSearch, "/invoices/issued/search", params)

    async def _post(self, path: str, payload: dict[str, Any], approval_token: str) -> Any:
        """A write: HMAC over the exact body + the single-use approval JWT. Never retried (MONEY_API §2).
        A refusal raises `BridgeRefused` (status + the bridge's `detail`); transport/5xx → `BridgeUnavailable`."""
        _circuit.check()
        body = json.dumps(payload, separators=(",", ":")).encode()
        stamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            "X-Bridge-Key-Id": self._key_id,
            "X-Bridge-Timestamp": stamp,
            "X-Bridge-Signature": sign(self._secret, "POST", path, stamp, body),
            "X-Approval-Token": approval_token,
        }
        try:
            resp = await self._http.post(self._base + path, content=body, headers=headers)
        except httpx.HTTPError as exc:
            _circuit.failure()
            raise BridgeUnavailable() from exc
        code = f"bridge_{resp.status_code}"
        detail: dict[str, Any] = {}
        try:
            raw = resp.json()["detail"]
            if isinstance(raw, dict):
                detail = raw
                code = str(raw["code"])
        except (ValueError, KeyError, TypeError):
            pass
        if resp.status_code == 501:
            raise BridgeUnavailable("waiting_for_probe")
        if resp.status_code >= 500:
            _circuit.failure()
            raise BridgeUnavailable(code)
        _circuit.success()
        if resp.status_code != 200:
            raise BridgeRefused(resp.status_code, code, detail)
        return resp.json()

    async def create_activity(self, payload: dict[str, Any], approval_token: str) -> ActivityOut:
        """Phase 3f write. A refusal keeps the old contract: `BridgeUnavailable(code)`."""
        try:
            data = await self._post("/activities", payload, approval_token)
        except BridgeRefused as exc:
            raise BridgeUnavailable(exc.code) from None
        try:
            return ActivityOut.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def create_article(self, payload: dict[str, Any], approval_token: str) -> ArticleCreated:
        """D32 (#239) `CreateArticle` — only Katalog, Názov, SMID and the main card of a variant. 409
        `catalog_exists` → `BridgeRefused`; a timeout is never retried here (the caller reconciles by catalog)."""
        data = await self._post("/articles", payload, approval_token)
        try:
            return ArticleCreated.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def create_delivery_note(self, payload: dict[str, Any], approval_token: str) -> DeliveryNoteCreated:
        """#247 / D33 `CreateReceivedDeliveryNote` as a koncept. 409 `duplicate` / 422 `not_koncept` →
        `BridgeRefused`; transport errors and 5xx → `BridgeUnavailable` (the caller reconciles by SMID)."""
        data = await self._post("/delivery-notes/received", payload, approval_token)
        try:
            return DeliveryNoteCreated.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def received_notes(self, centre_id: uuid.UUID, count: int = 20) -> list[ReceivedNoteRow]:
        """Settings 11e „Vybrať iný“: the newest received delivery notes of the branch centre."""
        return await self._list(
            ReceivedNoteRow, "/delivery-notes/received", {"centre_id": str(centre_id), "count": count}
        )

    async def delivery_note_template(self, note_id: uuid.UUID) -> DeliveryNoteTemplate | None:
        data = await self._get(f"/delivery-notes/received/{note_id}/template", allow_404=True)
        if data is None:
            return None
        try:
            return DeliveryNoteTemplate.model_validate(data)
        except ValidationError as exc:
            raise BridgeUnavailable("bridge_contract") from exc

    async def catalog_free(self, katalog: str) -> CatalogFree:
        """D32 live check of a catalog number (exact match, deleted cards ignored)."""
        return await self._model(CatalogFree, "/articles/catalog-free", {"katalog": katalog})

    async def invoice_pdf(self, kind: str, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        """The original Money PDF (never rendered by Smart Mail, DOCUMENTS_SPEC §6); None = not found."""
        return await self._pdf(f"/invoices/issued/{kind}/{invoice_id}/pdf?{urlencode({'report_id': report_id})}")

    async def document_pdf(
        self, kind: str, record_id: uuid.UUID, report_id: str, design_id: str | None = None
    ) -> bytes | None:
        """#222 Money's own print report through `/pdfreport` (read only); None = not found."""
        params = {"report_id": report_id, **({"design_id": design_id} if design_id else {})}
        return await self._pdf(f"/documents/{kind}/{record_id}/pdf?{urlencode(params)}")

    async def search_deliveries(
        self, *, number: str | None = None, order: str | None = None, company_id: uuid.UUID | None = None
    ) -> DeliverySearch:
        """#222 issued delivery notes: number → order in Popis/Poznámka → the company's latest."""
        params = {"number": number, "order": order, "company_id": str(company_id) if company_id else None}
        return await self._model(DeliverySearch, "/delivery-notes/issued/search", params)

    async def _pdf(self, path_qs: str) -> bytes | None:
        _circuit.check()
        stamp = str(int(time.time()))
        headers = {
            "X-Bridge-Key-Id": self._key_id,
            "X-Bridge-Timestamp": stamp,
            "X-Bridge-Signature": sign(self._secret, "GET", path_qs, stamp),
        }
        try:
            resp = await self._http.get(self._base + path_qs, headers=headers)
        except httpx.HTTPError as exc:
            _circuit.failure()
            raise BridgeUnavailable() from exc
        if resp.status_code >= 500 or resp.status_code in (401, 403):
            _circuit.failure()
            raise BridgeUnavailable()
        _circuit.success()
        if resp.status_code == 404:
            return None
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            raise BridgeUnavailable(f"bridge_{resp.status_code}")
        return resp.content

    async def codebook(self, name: CodebookName, start: int, count: int) -> CodebookPage:
        return await self._model(CodebookPage, f"/sync/codebooks/{name}", {"from": start, "count": count})
