"""Small security primitives: tokens, password fingerprints, encryption at rest, signed cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


def new_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_fingerprint(password: str, salt: bytes | None = None) -> str:
    """Slow salted hash of the mailbox password. Used only to notice that the password changed on the mail server
    (PRODUCT_SPEC §2.0) — Smart Mail never verifies a login against it, the IMAP server always does."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def fingerprint_matches(password: str, fingerprint: str) -> bool:
    try:
        scheme, salt_b64, _ = fingerprint.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    return hmac.compare_digest(password_fingerprint(password, base64.b64decode(salt_b64)), fingerprint)


def _fernet(settings: Settings) -> Fernet:
    if settings.app_encryption_key is not None:
        return Fernet(settings.app_encryption_key.get_secret_value().encode())
    # dev/test only (prod requires APP_ENCRYPTION_KEY, see Settings): derive a key from the secret key
    derived = hashlib.sha256(b"smartmail-dev-fernet|" + settings.app_secret_key.get_secret_value().encode()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, ciphertext: str) -> str:
    try:
        return _fernet(settings).decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("cannot decrypt value (APP_ENCRYPTION_KEY changed?)") from exc


def _sign(settings: Settings, purpose: str, message: str) -> str:
    key = settings.app_secret_key.get_secret_value().encode()
    mac = hmac.new(key, f"{purpose}|{message}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


# --- CSRF: signed double-submit token bound to the current session cookie (OWASP) -------------------------------
def csrf_token(settings: Settings, session_token: str | None) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_sign(settings, 'csrf', f'{nonce}|{session_token or ""}')}"


def csrf_valid(settings: Settings, token: str, session_token: str | None) -> bool:
    nonce, _, sig = token.partition(".")
    if not nonce or not sig:
        return False
    return hmac.compare_digest(sig.encode(), _sign(settings, "csrf", f"{nonce}|{session_token or ''}").encode())


# --- "Zapamätať zariadenie na 30 dní" after 2FA (SCREENS_SPEC W1a) ------------------------------------------------
def mfa_trust_cookie(settings: Settings, account_id: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + settings.mfa_trust_days * 86400)
    return f"{account_id}.{expires}.{_sign(settings, 'mfa-trust', f'{account_id}|{expires}')}"


def mfa_trust_valid(settings: Settings, cookie: str | None, account_id: str, now: float | None = None) -> bool:
    if not cookie:
        return False
    parts = cookie.split(".")
    if len(parts) != 3 or parts[0] != account_id or not parts[1].isdigit():
        return False
    if int(parts[1]) < (now or time.time()):
        return False
    return hmac.compare_digest(parts[2].encode(), _sign(settings, "mfa-trust", f"{account_id}|{parts[1]}").encode())
