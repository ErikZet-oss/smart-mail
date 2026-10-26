"""TOTP (RFC 6238, SHA-1, 30 s, 6 digits — what every authenticator app supports) and backup codes.

Implemented with the standard library; enrolment (QR code, 10 backup codes) is part of Settings 09 Bezpečnosť.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import struct

STEP_S = 30
DIGITS = 6
WINDOW = 1  # accept the previous and the next step (clock drift)
BACKUP_CODE = re.compile(r"^[a-z0-9]{4}-?[a-z0-9]{4}$")


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret_b32: str) -> bytes:
    padded = secret_b32.upper() + "=" * (-len(secret_b32) % 8)
    return base64.b32decode(padded)


def code_at(secret_b32: str, step: int) -> str:
    mac = hmac.new(_key(secret_b32), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**DIGITS).zfill(DIGITS)


def verify(secret_b32: str, code: str, now: float, last_step: int | None) -> int | None:
    """Return the matched time step, or None. A step that was already used (`last_step`) is rejected (replay)."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    current = int(now // STEP_S)
    for step in range(current - WINDOW, current + WINDOW + 1):
        if last_step is not None and step <= last_step:
            continue
        if hmac.compare_digest(code_at(secret_b32, step), code):
            return step
    return None


def new_backup_codes(count: int = 10) -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return [
        "".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(secrets.choice(alphabet) for _ in range(4))
        for _ in range(count)
    ]


def normalize_backup_code(code: str) -> str | None:
    code = code.strip().lower().replace(" ", "")
    if not BACKUP_CODE.match(code):
        return None
    return code.replace("-", "")


def hash_backup_code(code: str) -> str:
    normalized = normalize_backup_code(code)
    if normalized is None:
        raise ValueError("invalid backup code format")
    return hashlib.sha256(normalized.encode()).hexdigest()


def use_backup_code(code: str, hashes: list[str]) -> list[str] | None:
    """Return the remaining hashes when `code` matches one (single use), else None."""
    normalized = normalize_backup_code(code)
    if normalized is None:
        return None
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    for h in hashes:
        if hmac.compare_digest(h, digest):
            return [x for x in hashes if x != h]
    return None
