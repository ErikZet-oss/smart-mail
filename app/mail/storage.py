"""Object storage for raw messages and attachments (CLAUDE.md §2, ADR-002 / ADR-007).

Phase 1e uses the S3 API (SeaweedFS in compose, any S3-compatible store in prod). Keys stay opaque so callers
never depend on the backend. A local filesystem backend remains for unit tests that set STORAGE_BACKEND=local.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError

from app.core.config import Settings

Backend = Literal["s3", "local"]


def _backend(settings: Settings) -> Backend:
    return settings.storage_backend


def _s3(settings: Settings) -> Any:
    if not settings.s3_access_key or not settings.s3_secret_key:
        raise RuntimeError("S3_ACCESS_KEY and S3_SECRET_KEY are required when STORAGE_BACKEND=s3")
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        region_name="us-east-1",
    )


def ensure_bucket(settings: Settings) -> None:
    """Create the bucket when missing (dev SeaweedFS starts empty)."""
    if _backend(settings) != "s3":
        return
    client = _s3(settings)
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.s3_bucket)


def _local_root(settings: Settings) -> Path:
    path = Path(settings.storage_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def put_bytes(settings: Settings, data: bytes, *, prefix: str) -> tuple[str, str]:
    """Store bytes; return (storage_key, sha256 hex)."""
    digest = hashlib.sha256(data).hexdigest()
    key = f"{prefix.strip('/')}/{digest[:2]}/{digest[2:4]}/{uuid.uuid4().hex}"
    if _backend(settings) == "local":
        target = _local_root(settings) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return key, digest
    ensure_bucket(settings)
    _s3(settings).put_object(Bucket=settings.s3_bucket, Key=key, Body=data)
    return key, digest


def get_bytes(settings: Settings, key: str) -> bytes | None:
    if not key:
        return None
    if _backend(settings) == "local":
        path = _local_root(settings) / key
        if not path.is_file():
            return None
        return path.read_bytes()
    try:
        response = _s3(settings).get_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    body = response["Body"].read()
    return bytes(body)


def delete_key(settings: Settings, key: str) -> None:
    if not key:
        return
    if _backend(settings) == "local":
        path = _local_root(settings) / key
        if path.is_file():
            path.unlink()
        return
    try:
        _s3(settings).delete_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError:
        return


CHUNK = 1024 * 1024


def put_file(settings: Settings, path: Path, *, prefix: str) -> tuple[str, str]:
    """Store a file from disk without reading it into memory (large exports, #127); return (storage_key, sha256).
    S3: boto3 `upload_file` sends it in parts."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            digest.update(block)
    sha = digest.hexdigest()
    key = f"{prefix.strip('/')}/{sha[:2]}/{sha[2:4]}/{uuid.uuid4().hex}"
    if _backend(settings) == "local":
        target = _local_root(settings) / key
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as src, target.open("wb") as dst:
            for block in iter(lambda: src.read(CHUNK), b""):
                dst.write(block)
        return key, sha
    ensure_bucket(settings)
    _s3(settings).upload_file(str(path), settings.s3_bucket, key)
    return key, sha


def iter_key(settings: Settings, key: str) -> Iterator[bytes] | None:
    """Stream a stored object in 1 MB blocks (downloads of large exports); None when it is gone."""
    if not key:
        return None
    if _backend(settings) == "local":
        path = _local_root(settings) / key
        if not path.is_file():
            return None

        def _local() -> Iterator[bytes]:
            with path.open("rb") as fh:
                yield from iter(lambda: fh.read(CHUNK), b"")

        return _local()
    try:
        response = _s3(settings).get_object(Bucket=settings.s3_bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code", "") in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    body = response["Body"]

    def _s3_chunks() -> Iterator[bytes]:
        for block in body.iter_chunks(CHUNK):
            yield bytes(block)

    return _s3_chunks()
