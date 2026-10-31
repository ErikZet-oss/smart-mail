"""The main app's only way to Money: HMAC-signed GETs to the bridge (MONEY_API §6, signature as `bridge/app/auth.py`).

Money or the bridge being down must never break mail: every failure becomes `BridgeUnavailable`, and after
`FAILS_TO_OPEN` failures in a row the circuit stays open for `OPEN_SECONDS` (calls fail fast, the UI shows
„Money nedostupné“).
"""

from __future__ import annotations

import hashlib
import hmac
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
    CodebookName,
    CodebookPage,
    Company,
    CompanyPage,
    Delivery,
    Health,
    InvoiceSearch,
    IssuedInvoice,
    Order,
    PersonPage,
)

TIMEOUT = httpx.Timeout(15.0, connect=3.0)
FAILS_TO_OPEN = 3
OPEN_SECONDS = 60.0
M = TypeVar("M", bound=BaseModel)


class BridgeUnavailable(Exception):
    def __init__(self, code: str = "money_unavailable") -> None:
        super().__init__(code)
        self.code = code


def sign(secret: str, method: str, path_qs: str, timestamp: str, body: bytes = b"") -> str:
    """Must stay byte-identical to `bridge/app/auth.py` (test vector in tests/test_money_bridge_client_3b.py)."""
    canonical = "\n".join([method.upper(), path_qs, timestamp, hashlib.sha256(body).hexdigest()]).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()


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
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT)

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
        query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
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

    async def search_invoices(
        self, *, number: str | None = None, vs: str | None = None, company_id: uuid.UUID | None = None
    ) -> InvoiceSearch:
        """MONEY_API §5.1 cascade in the bridge. A value with `~ # | ( )` answers 422 there → `bridge_422`."""
        params = {"number": number, "vs": vs, "company_id": str(company_id) if company_id else None}
        return await self._model(InvoiceSearch, "/invoices/issued/search", params)

    async def invoice_pdf(self, kind: str, invoice_id: uuid.UUID, report_id: str) -> bytes | None:
        """The original Money PDF (never rendered by Smart Mail, DOCUMENTS_SPEC §6); None = not found."""
        _circuit.check()
        path_qs = f"/invoices/issued/{kind}/{invoice_id}/pdf?{urlencode({'report_id': report_id})}"
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
