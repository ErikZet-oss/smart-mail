"""Phase 0 acceptance: liveness never depends on other services; readiness reports DB/Redis honestly."""

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def _unreachable_settings() -> Settings:
    # port 1 refuses immediately -> readiness must fail fast and say which dependency is down
    return Settings(
        app_env="test",
        database_url="postgresql+asyncpg://x:y@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    )


def test_healthz_ok_without_dependencies() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readyz_503_when_dependencies_down() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        r = client.get("/readyz")
    assert r.status_code == 503
    assert r.json() == {"status": "not_ready", "checks": {"database": False, "redis": False}}


def test_version_endpoint() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["env"] == "test"


def test_openapi_docs_disabled_outside_dev() -> None:
    with TestClient(create_app(_unreachable_settings())) as client:
        assert client.get("/api/docs").status_code == 404
        assert client.get("/api/openapi.json").status_code == 404


def test_openapi_docs_enabled_in_dev() -> None:
    settings = Settings(
        app_env="dev",
        database_url="postgresql+asyncpg://x:y@127.0.0.1:1/none",
        redis_url="redis://127.0.0.1:1/0",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/openapi.json").status_code == 200
        assert client.get("/api/docs").status_code == 200
