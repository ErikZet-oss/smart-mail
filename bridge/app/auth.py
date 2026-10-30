"""HMAC between the main app and the bridge (CLAUDE.md §7, MONEY_API §6).

Headers: `X-Bridge-Key-Id`, `X-Bridge-Timestamp` (unix seconds), `X-Bridge-Signature` =
hex HMAC-SHA256(secret, "METHOD\\nPATH?QUERY\\nTIMESTAMP\\nsha256(body)"). Allowed clock skew ±5 min; a signature is
accepted once (replay cache for the skew window). The main app signs with the same function (test vector in
`tests/test_auth.py`).
"""

from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

SKEW_SECONDS = 300


def canonical(method: str, path_qs: str, timestamp: str, body: bytes) -> bytes:
    return "\n".join([method.upper(), path_qs, timestamp, hashlib.sha256(body).hexdigest()]).encode()


def sign(secret: str, method: str, path_qs: str, timestamp: str, body: bytes = b"") -> str:
    return hmac.new(secret.encode(), canonical(method, path_qs, timestamp, body), hashlib.sha256).hexdigest()


class ReplayCache:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}

    def check_and_add(self, signature: str, now: float) -> bool:
        if len(self._seen) > 10_000 or any(exp < now for exp in list(self._seen.values())[:64]):
            self._seen = {s: exp for s, exp in self._seen.items() if exp >= now}
        if signature in self._seen:
            return False
        self._seen[signature] = now + 2 * SKEW_SECONDS
        return True


def _deny(code: str) -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code})


async def verify_request(request: Request, *, key_id: str, secret: str, replay: ReplayCache) -> None:
    headers = request.headers
    if headers.get("x-bridge-key-id") != key_id:
        raise _deny("hmac_key_unknown")
    timestamp = headers.get("x-bridge-timestamp", "")
    signature = headers.get("x-bridge-signature", "")
    if not timestamp.isdigit() or not signature:
        raise _deny("hmac_missing")
    now = time.time()
    if abs(now - int(timestamp)) > SKEW_SECONDS:
        raise _deny("hmac_expired")
    path_qs = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    expected = sign(secret, request.method, path_qs, timestamp, await request.body())
    if not hmac.compare_digest(expected, signature):
        raise _deny("hmac_invalid")
    if not replay.check_and_add(signature, now):
        raise _deny("hmac_replayed")
