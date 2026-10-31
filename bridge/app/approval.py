"""Single-use approval tokens for Money writes (CLAUDE.md §7, MONEY_API §6; Erik's answers in #144).

The app signs an Ed25519 JWT (EdDSA) for every write; the bridge checks the signature with the public key, the
action, `exp` (max 5 min), the sha256 of the exact request body and that `jti` was not used before. A write without a
valid token is refused — on the mock too. The key arrives as a PEM or as base64 of the PEM (one line in `.env`).
"""

from __future__ import annotations

import base64
import hashlib
import time

import jwt
from fastapi import HTTPException

MAX_LIFETIME_S = 300
LEEWAY_S = 30


def load_key(raw: str) -> str:
    text = raw.strip()
    if text.startswith("-----BEGIN"):
        return text
    return base64.b64decode(text).decode("ascii")


class JtiCache:
    """Used token ids until they expire (the bridge is one process — NSSM service, ADR-016)."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def use(self, jti: str, exp: int, now: float) -> bool:
        self._seen = {k: v for k, v in self._seen.items() if v >= now - LEEWAY_S}
        if jti in self._seen:
            return False
        self._seen[jti] = exp
        return True


def _deny(code: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code})


def verify_approval(
    token: str | None, *, public_key: str | None, action: str, body: bytes, jtis: JtiCache
) -> dict[str, object]:
    if not public_key:
        raise _deny("writes_disabled")
    if not token:
        raise _deny("approval_missing")
    try:
        claims = jwt.decode(
            token,
            load_key(public_key),
            algorithms=["EdDSA"],
            options={"require": ["exp", "iat", "jti", "act", "sha256", "person_id"]},
            leeway=LEEWAY_S,
        )
    except jwt.ExpiredSignatureError:
        raise _deny("approval_expired") from None
    except (jwt.PyJWTError, ValueError):
        raise _deny("approval_invalid") from None
    now = time.time()
    if int(claims["exp"]) - int(claims["iat"]) > MAX_LIFETIME_S + 1:
        raise _deny("approval_invalid")
    if claims["act"] != action:
        raise _deny("approval_wrong_action")
    if claims["sha256"] != hashlib.sha256(body).hexdigest():
        raise _deny("approval_payload_mismatch")
    if not jtis.use(str(claims["jti"]), int(claims["exp"]), now):
        raise _deny("approval_replayed")
    return claims
