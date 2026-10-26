"""Pure security primitives: TOTP (RFC 6238), backup codes, CSRF, trust cookie, password fingerprint, Fernet."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.auth import totp
from app.auth.security import (
    csrf_token,
    csrf_valid,
    decrypt,
    encrypt,
    fingerprint_matches,
    mfa_trust_cookie,
    mfa_trust_valid,
    password_fingerprint,
)
from app.core.config import Settings

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
SETTINGS = Settings(app_env="test", app_secret_key="unit-test-secret-key-0123456789abcdef")


@pytest.mark.parametrize(
    ("t", "code"),
    [(59, "287082"), (1111111109, "081804"), (1234567890, "005924"), (2000000000, "279037")],
)
def test_totp_rfc6238_vectors(t: int, code: str) -> None:
    assert totp.code_at(RFC_SECRET, t // 30) == code
    assert totp.verify(RFC_SECRET, code, t, None) == t // 30


def test_totp_accepts_one_step_of_clock_drift_only() -> None:
    now = 1234567890
    step = now // 30
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step - 1), now, None) == step - 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), now, None) == step + 1
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step - 2), now, None) is None


def test_totp_replay_of_used_step_rejected() -> None:
    now = 1234567890
    code = totp.code_at(RFC_SECRET, now // 30)
    used = totp.verify(RFC_SECRET, code, now, None)
    assert used is not None
    assert totp.verify(RFC_SECRET, code, now, used) is None


@pytest.mark.parametrize("bad", ["", "12345", "1234567", "abcdef", "12 34 5"])
def test_totp_rejects_malformed(bad: str) -> None:
    assert totp.verify(RFC_SECRET, bad, 59, None) is None


def test_backup_codes_single_use_and_format_tolerant() -> None:
    codes = totp.new_backup_codes()
    assert len(codes) == 10 and len(set(codes)) == 10
    hashes = [totp.hash_backup_code(c) for c in codes]
    remaining = totp.use_backup_code(codes[3].upper().replace("-", " "), hashes)
    assert remaining is not None and len(remaining) == 9
    assert totp.use_backup_code(codes[3], remaining) is None
    assert totp.use_backup_code("zzzz-zzzz", hashes) is None
    assert totp.use_backup_code("not a code", hashes) is None


def test_new_secret_is_base32_160_bits() -> None:
    secret = totp.new_secret()
    assert len(secret) == 32
    totp.code_at(secret, 1)


def test_csrf_token_bound_to_session() -> None:
    token = csrf_token(SETTINGS, "session-a")
    assert csrf_valid(SETTINGS, token, "session-a")
    assert not csrf_valid(SETTINGS, token, "session-b")
    assert not csrf_valid(SETTINGS, token, None)
    assert csrf_valid(SETTINGS, csrf_token(SETTINGS, None), None)
    other = Settings(app_env="test", app_secret_key="another-secret-key-0123456789abcdef")
    assert not csrf_valid(other, token, "session-a")


@given(st.text(max_size=80))
def test_csrf_garbage_never_valid(garbage: str) -> None:
    assert not csrf_valid(SETTINGS, garbage, "session-a")


def test_mfa_trust_cookie_account_and_expiry() -> None:
    cookie = mfa_trust_cookie(SETTINGS, "acc-1", now=1_000_000)
    assert mfa_trust_valid(SETTINGS, cookie, "acc-1", now=1_000_000 + 29 * 86400)
    assert not mfa_trust_valid(SETTINGS, cookie, "acc-1", now=1_000_000 + 31 * 86400)
    assert not mfa_trust_valid(SETTINGS, cookie, "acc-2", now=1_000_000)
    tampered = cookie.rsplit(".", 1)[0] + ".x"
    assert not mfa_trust_valid(SETTINGS, tampered, "acc-1", now=1_000_000)
    assert not mfa_trust_valid(SETTINGS, None, "acc-1")


def test_password_fingerprint_salted_and_verifiable() -> None:
    fp = password_fingerprint("Heslo-123")
    assert fp.startswith("scrypt$") and "Heslo-123" not in fp
    assert fingerprint_matches("Heslo-123", fp)
    assert not fingerprint_matches("Heslo-124", fp)
    assert password_fingerprint("Heslo-123") != fp
    assert not fingerprint_matches("x", "garbage")


def test_encryption_round_trip() -> None:
    blob = encrypt(SETTINGS, "JBSWY3DPEHPK3PXP")
    assert "JBSWY3DPEHPK3PXP" not in blob
    assert decrypt(SETTINGS, blob) == "JBSWY3DPEHPK3PXP"
    other = Settings(app_env="test", app_secret_key="another-secret-key-0123456789abcdef")
    with pytest.raises(ValueError):
        decrypt(other, blob)


def test_prod_settings_require_strong_secrets() -> None:
    with pytest.raises(ValueError):
        Settings(app_env="prod")
    with pytest.raises(ValueError):
        Settings(app_env="prod", app_secret_key="x" * 40)  # no APP_ENCRYPTION_KEY
    with pytest.raises(ValueError):
        Settings(
            app_env="prod",
            app_secret_key="x" * 40,
            app_encryption_key="k" * 44,
            imap_login_security="none",
        )
