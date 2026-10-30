from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import sign
from app.backend import MoneyBackend
from app.config import BridgeSettings
from app.main import create_app
from app.mock import MockBackend

SECRET = "test-secret-not-dev"
KEY_ID = "test"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--money-live",
        action="store_true",
        help="also run the contract suite against the real Money TEST agenda (MONEY_* env, agenda TEST only)",
    )


class SignedClient:
    """TestClient that signs every request like the main app does."""

    def __init__(self, client: TestClient, secret: str = SECRET, key_id: str = KEY_ID) -> None:
        self.client, self.secret, self.key_id = client, secret, key_id

    def headers(self, method: str, path_qs: str, body: bytes = b"", ts: int | None = None) -> dict[str, str]:
        stamp = str(ts if ts is not None else int(time.time()))
        return {
            "X-Bridge-Key-Id": self.key_id,
            "X-Bridge-Timestamp": stamp,
            "X-Bridge-Signature": sign(self.secret, method, path_qs, stamp, body),
        }

    def get(self, path_qs: str, **kwargs: Any) -> Any:
        return self.client.get(path_qs, headers=self.headers("GET", path_qs), **kwargs)


def bridge_settings(**overrides: Any) -> BridgeSettings:
    values: dict[str, Any] = {"money_backend": "mock", "bridge_hmac_key_id": KEY_ID, "bridge_hmac_secret": SECRET}
    values.update(overrides)
    return BridgeSettings(**values)


def make_client(backend: MoneyBackend | None = None, **overrides: Any) -> SignedClient:
    app = create_app(bridge_settings(**overrides), backend=backend or MockBackend())
    return SignedClient(TestClient(app))


@pytest.fixture
def mock_client() -> SignedClient:
    return make_client()


def _live_backend() -> MoneyBackend:
    from app.api_backend import ApiBackend

    settings = BridgeSettings()
    if settings.money_backend != "api" or settings.money_agenda_label != "TEST":
        pytest.fail("--money-live needs MONEY_BACKEND=api and MONEY_AGENDA_LABEL=TEST")
    return ApiBackend(settings)


@pytest.fixture(params=["mock", "live"])
def contract_client(request: pytest.FixtureRequest) -> Iterator[SignedClient]:
    if request.param == "live":
        if not request.config.getoption("--money-live") or not os.environ.get("MONEY_BASE_URL"):
            pytest.skip("contract against the TEST agenda runs only with --money-live")
        with TestClient(create_app(bridge_settings(money_backend="api"), backend=_live_backend())) as client:
            yield SignedClient(client)
        return
    yield make_client()
