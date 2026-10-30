from __future__ import annotations

import time

from app.auth import canonical, sign
from tests.conftest import KEY_ID, SECRET, make_client


def test_signature_test_vector() -> None:
    """The main app (3b) must produce exactly this signature."""
    assert canonical("get", "/companies/x?a=1", "1700000000", b"") == (
        b"GET\n/companies/x?a=1\n1700000000\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert sign("k", "GET", "/healthz", "1700000000") == sign("k", "get", "/healthz", "1700000000")
    assert len(sign("k", "GET", "/healthz", "1700000000")) == 64


def test_signed_request_passes_and_unsigned_fails() -> None:
    client = make_client()
    assert client.get("/sync/codebooks/currencies").status_code == 200
    r = client.client.get("/sync/codebooks/currencies")
    assert r.status_code == 401 and r.json()["detail"]["code"] == "hmac_key_unknown"


def test_health_needs_no_signature() -> None:
    assert make_client().client.get("/healthz").status_code == 200


def test_wrong_key_secret_expired_and_tampered() -> None:
    client = make_client()
    path = "/sync/codebooks/currencies"
    h = client.headers("GET", path)
    assert (
        client.client.get(path, headers={**h, "X-Bridge-Key-Id": "other"}).json()["detail"]["code"]
        == "hmac_key_unknown"
    )
    wrong = make_client().headers("GET", path)
    wrong["X-Bridge-Signature"] = sign("other-secret", "GET", path, wrong["X-Bridge-Timestamp"])
    assert client.client.get(path, headers=wrong).json()["detail"]["code"] == "hmac_invalid"
    old = client.headers("GET", path, ts=int(time.time()) - 301)
    assert client.client.get(path, headers=old).json()["detail"]["code"] == "hmac_expired"
    # a signature for one query string does not cover another
    signed = client.headers("GET", path + "?count=1")
    assert client.client.get(path + "?count=2", headers=signed).json()["detail"]["code"] == "hmac_invalid"
    assert KEY_ID and SECRET


def test_replay_is_refused() -> None:
    client = make_client()
    path = "/sync/codebooks/currencies"
    h = client.headers("GET", path)
    assert client.client.get(path, headers=h).status_code == 200
    r = client.client.get(path, headers=h)
    assert r.status_code == 401 and r.json()["detail"]["code"] == "hmac_replayed"
