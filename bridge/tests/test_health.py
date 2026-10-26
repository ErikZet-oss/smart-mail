from fastapi.testclient import TestClient

from app.config import BridgeSettings
from app.main import create_app


def test_mock_bridge_is_healthy_and_never_writes() -> None:
    client = TestClient(create_app(BridgeSettings(money_backend="mock")))
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["backend"] == "mock"
    assert body["agenda"] == "TEST"
    assert body["writes_enabled"] is False
    assert client.get("/readyz").status_code == 200


def test_api_backend_without_credentials_is_not_ready() -> None:
    client = TestClient(create_app(BridgeSettings(money_backend="api")))
    r = client.get("/readyz")
    assert r.status_code == 503


def test_prod_agenda_does_not_enable_writes() -> None:
    s = BridgeSettings(money_backend="api", money_agenda_label="PROD", money_base_url="https://x", money_client_id="c")
    assert s.writes_enabled is False
