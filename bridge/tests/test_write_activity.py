"""Phase 3f: POST /activities needs HMAC + a single-use Ed25519 approval JWT bound to the body; mock is idempotent."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.mock import MockBackend
from tests.conftest import make_client

COMPANY = uuid.uuid5(uuid.NAMESPACE_URL, "company:1")


def keys() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    priv_pem = private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return priv_pem, base64.b64encode(pub_pem).decode()  # the public key as one base64 line, like in .env


PRIV, PUB = keys()


def token(body: bytes, **over: Any) -> str:
    now = int(time.time())
    claims = {
        "act": "activity.create",
        "company_id": str(COMPANY),
        "sha256": hashlib.sha256(body).hexdigest(),
        "person_id": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 300,
        "jti": uuid.uuid4().hex,
    }
    claims.update(over)
    return jwt.encode(claims, over.pop("key", PRIV), algorithm="EdDSA")


def body(**over: Any) -> bytes:
    data = {
        "company_id": str(COMPANY),
        "type_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "activity-type:1")),
        "subject": "Kópia faktúry",
        "description": "Faktúry: FV2600042",
        "smid": f"SMID:{uuid.UUID(int=7)}",
    }
    data.update(over)
    return json.dumps(data).encode()


_TS = [int(time.time()) - 200]


def post(client: Any, raw: bytes, tok: str | None) -> Any:
    _TS[0] += 1  # a fresh HMAC timestamp per call: the HMAC replay cache must not hide the approval checks
    headers = client.headers("POST", "/activities", raw, ts=_TS[0])
    if tok:
        headers["X-Approval-Token"] = tok
    return client.client.post("/activities", content=raw, headers={**headers, "Content-Type": "application/json"})


@pytest.fixture
def client() -> Any:
    return make_client(backend=MockBackend(), approval_jwt_public_key=PUB)


def test_3f_valid_token_creates_once_then_idempotent(client: Any) -> None:
    raw = body()
    r = post(client, raw, token(raw))
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["created"] is True
    again = post(client, raw, token(raw))  # a new token, same SMID → no second activity
    assert again.json() == {"id": first["id"], "created": False}


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"act": "order.create"}, "approval_wrong_action"),
        ({"sha256": "0" * 64}, "approval_payload_mismatch"),
        ({"exp": int(time.time()) - 120}, "approval_expired"),
        ({"company_id": str(uuid.uuid4())}, "approval_wrong_company"),
        ({"iat": int(time.time()), "exp": int(time.time()) + 3600}, "approval_invalid"),
    ],
)
def test_3f_bad_tokens_are_refused(client: Any, over: dict[str, Any], code: str) -> None:
    raw = body()
    r = post(client, raw, token(raw, **over))
    assert r.status_code == 403 and r.json()["detail"]["code"] == code


def test_3f_missing_foreign_and_replayed_tokens(client: Any) -> None:
    raw = body()
    assert post(client, raw, None).json()["detail"]["code"] == "approval_missing"
    other_priv, _ = keys()
    assert post(client, raw, token(raw, key=other_priv)).json()["detail"]["code"] == "approval_invalid"
    tok = token(raw)
    assert post(client, raw, tok).status_code == 200
    assert post(client, raw, tok).json()["detail"]["code"] == "approval_replayed"


def test_3f_no_public_key_means_no_writes() -> None:
    client = make_client(backend=MockBackend())
    raw = body()
    r = post(client, raw, token(raw))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "writes_disabled"
    assert client.client.get("/healthz").json()["writes_enabled"] is False


def test_3f_unsigned_request_is_refused_before_the_token(client: Any) -> None:
    raw = body()
    r = client.client.post("/activities", content=raw, headers={"X-Approval-Token": token(raw)})
    assert r.status_code == 401


def test_3f_body_is_validated(client: Any) -> None:
    raw = body(smid="SMID:not-a-uuid")
    assert post(client, raw, token(raw)).status_code == 422


def test_3f_api_backend_waits_for_the_probe() -> None:
    from app.api_backend import ApiBackend
    from tests.test_api_backend import settings

    client = make_client(backend=ApiBackend(settings()), approval_jwt_public_key=PUB)
    raw = body()
    r = post(client, raw, token(raw))
    assert r.status_code == 501 and r.json()["detail"]["code"] == "waiting_for_probe"
