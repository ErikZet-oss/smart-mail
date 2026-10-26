"""Local file storage for raw messages and attachments (CLAUDE.md §2: local driver in dev).

S3-compatible storage stays for Phase 7 hardening; keys are opaque paths under STORAGE_PATH so a later
driver can swap the backend without changing callers.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from app.core.config import Settings


def _root(settings: Settings) -> Path:
    path = Path(settings.storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def put_bytes(settings: Settings, data: bytes, *, prefix: str) -> tuple[str, str]:
    """Store bytes; return (storage_key, sha256 hex)."""
    digest = hashlib.sha256(data).hexdigest()
    key = f"{prefix}/{digest[:2]}/{digest[2:4]}/{uuid.uuid4().hex}"
    target = _root(settings) / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return key, digest


def get_bytes(settings: Settings, key: str) -> bytes | None:
    path = _root(settings) / key
    if not path.is_file():
        return None
    return path.read_bytes()


def delete_key(settings: Settings, key: str) -> None:
    path = _root(settings) / key
    if path.is_file():
        path.unlink()
