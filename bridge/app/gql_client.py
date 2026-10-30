"""HTTP access to Money S4: token (client_credentials, scope S5Api), GraphQL and REST (MONEY_API §1–§2).

- Token cached until `expires_in − 60 s`, single-flight refresh, one retry on 401.
- Responses are parsed with `parse_float=Decimal` — no float ever holds a Money amount.
- Read-only: there is no mutation helper. Mutations come in Phase 4 and are never retried automatically.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

import httpx

from app.backend import MoneyError, MoneyUnavailable

QUERIES = Path(__file__).parent / "queries"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)


@cache
def load_query(name: str) -> str:
    return (QUERIES / f"{name}.graphql").read_text(encoding="utf-8")


def _json(resp: httpx.Response) -> Any:
    return json.loads(resp.content, parse_float=Decimal)


class TokenProvider:
    def __init__(self, http: httpx.AsyncClient, base_url: str, client_id: str, client_secret: str, scope: str) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/connect/token"
        self._form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": scope,
        }
        self._token: str | None = None
        self._valid_until = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        if self._token and time.monotonic() < self._valid_until:
            return self._token
        async with self._lock:  # single flight: concurrent callers wait for one refresh
            if self._token and time.monotonic() < self._valid_until:
                return self._token
            try:
                resp = await self._http.post(self._url, data=self._form)
            except httpx.HTTPError as exc:
                raise MoneyUnavailable("token request failed") from exc
            if resp.status_code != 200:
                raise MoneyUnavailable(f"token request answered {resp.status_code}")
            body = _json(resp)
            self._token = str(body["access_token"])
            self._valid_until = time.monotonic() + max(int(body.get("expires_in", 300)) - 60, 0)
            return self._token

    def invalidate(self, token: str) -> None:
        if self._token == token:
            self._token = None
            self._valid_until = 0.0


class MoneyHttp:
    def __init__(self, http: httpx.AsyncClient, tokens: TokenProvider, base_url: str, rest_version: str) -> None:
        self._http = http
        self._tokens = tokens
        self._base = base_url.rstrip("/")
        self._rest = rest_version.strip("/")

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in (1, 2):
            token = await self._tokens.get()
            try:
                resp = await self._http.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kwargs)
            except httpx.HTTPError as exc:
                raise MoneyUnavailable(f"{method} failed") from exc
            if resp.status_code == 401 and attempt == 1:
                self._tokens.invalidate(token)
                continue
            if resp.status_code >= 500 or resp.status_code == 401:
                raise MoneyUnavailable(f"Money answered {resp.status_code}")
            return resp
        raise MoneyUnavailable("unreachable")  # pragma: no cover

    async def graphql(self, name: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run `queries/<name>.graphql` (read queries only) and return `data`."""
        resp = await self._send(
            "POST", f"{self._base}/graphql", json={"query": load_query(name), "variables": variables or {}}
        )
        if resp.status_code != 200:
            raise MoneyError(f"graphql {name} answered {resp.status_code}")
        body = _json(resp)
        if body.get("errors"):
            raise MoneyError(f"graphql {name}: {len(body['errors'])} error(s)")  # never log the payload
        data = body.get("data")
        if not isinstance(data, dict):
            raise MoneyError(f"graphql {name}: no data")
        return data

    async def rest_json(self, path: str, params: dict[str, str] | None = None) -> Any:
        resp = await self._send("GET", f"{self._base}/{self._rest}/{path.lstrip('/')}", params=params)
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise MoneyError(f"REST {path.split('/')[0]} answered {resp.status_code}")
        return _json(resp)

    async def rest_bytes(self, path: str) -> bytes | None:
        resp = await self._send("GET", f"{self._base}/{self._rest}/{path.lstrip('/')}")
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise MoneyError(f"REST report answered {resp.status_code}")
        return resp.content
