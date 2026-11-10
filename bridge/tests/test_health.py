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
        (  # #212: PROD is allowed for reading, but never with the development HMAC secret
            {
                "money_agenda_label": "PROD",
                "money_base_url": "https://x",
                "money_client_id": "c",
                "money_client_secret": "s",
            },
            "BRIDGE_HMAC_SECRET",
        ),
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


def test_212_prod_with_real_api_starts_read_only() -> None:
    s = BridgeSettings(
        money_backend="api",
        money_agenda_label="PROD",
        money_base_url="https://x",
        money_client_id="c",
        money_client_secret="s",  # type: ignore[arg-type]
        bridge_hmac_secret="prod-secret",  # type: ignore[arg-type]
        approval_jwt_public_key="a-key-is-set",
    )
    assert s.startup_problem() is None
    assert s.read_only is True and s.writes_enabled is False  # even with the approval key
    app = create_app(s, backend=MockBackend())
    assert TestClient(app).get("/healthz").json()["agenda"] == "PROD"
