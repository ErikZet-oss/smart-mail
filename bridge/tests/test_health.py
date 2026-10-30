import pytest
from fastapi.testclient import TestClient

from app.config import BridgeSettings
from app.main import create_app
from app.mock import MockBackend


def test_mock_bridge_is_healthy_and_never_writes() -> None:
    client = TestClient(create_app(BridgeSettings(money_backend="mock"), backend=MockBackend()))
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"
    assert body["agenda"] == "TEST"
    assert body["writes_enabled"] is False
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json()["money_version"] == "mock"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"money_base_url": "https://x", "money_client_id": "c", "money_client_secret": "s"}, "BRIDGE_HMAC_SECRET"),
        ({"money_agenda_label": "PROD", "bridge_hmac_secret": "s", "money_base_url": "https://x"}, "TEST"),
        ({"bridge_hmac_secret": "s"}, "MONEY_BASE_URL"),
    ],
)
def test_api_backend_refuses_to_start(overrides: dict[str, str], reason: str) -> None:
    s = BridgeSettings(money_backend="api", **overrides)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match=reason):
        create_app(s)


def test_prod_agenda_does_not_enable_writes() -> None:
    s = BridgeSettings(money_backend="api", money_agenda_label="PROD", money_base_url="https://x", money_client_id="c")
    assert s.writes_enabled is False
