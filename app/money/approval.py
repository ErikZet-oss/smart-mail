"""Single-use approval token for Money writes (CLAUDE.md §7; Erik's answers in #144): Ed25519 JWT (EdDSA), 5 min,
bound to the exact request body (sha256), the action, the company and the person. The private key stays on the VPS
(`APPROVAL_JWT_PRIVATE_KEY`, PEM or base64 of the PEM) and is never logged."""

from __future__ import annotations

import base64
import hashlib
import time
import uuid

import jwt

from app.core.config import Settings

LIFETIME_S = 300


class ApprovalKeyMissing(Exception):
    pass


def _private_key(settings: Settings) -> str:
    if settings.approval_jwt_private_key is None:
        raise ApprovalKeyMissing()
    raw = settings.approval_jwt_private_key.get_secret_value().strip()
    if not raw:
        raise ApprovalKeyMissing()
    return raw if raw.startswith("-----BEGIN") else base64.b64decode(raw).decode("ascii")


def sign_approval(
    settings: Settings, *, action: str, company_id: uuid.UUID, person_id: uuid.UUID | None, body: bytes
) -> str:
    now = int(time.time())
    claims = {
        "act": action,
        "company_id": str(company_id),
        "person_id": str(person_id) if person_id else "",
        "sha256": hashlib.sha256(body).hexdigest(),
        "iat": now,
        "exp": now + LIFETIME_S,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(claims, _private_key(settings), algorithm="EdDSA")
