"""ClamAV attachment scanning (CLAUDE.md §11). Soft-fail: unreachable daemon → skipped."""

from __future__ import annotations

import asyncio
import contextlib
import struct
from typing import Literal

import structlog

from app.core.config import Settings

log = structlog.get_logger(__name__)

AvStatus = Literal["clean", "infected", "skipped", "error"]
CLAMD_PORT = 3310
CHUNK = 1024 * 1024


async def scan_bytes(settings: Settings, data: bytes) -> AvStatus:
    """Scan raw bytes via clamd INSTREAM. Never raises — mail must keep working when ClamAV is down."""
    host = (settings.clamav_host or "").strip()
    if not host or host.lower() in {"off", "none", "disabled"}:
        return "skipped"
    try:
        return await asyncio.wait_for(_instream(host, data), timeout=30)
    except TimeoutError:
        log.warning("clamav.timeout", host=host)
        return "error"
    except OSError as exc:
        log.warning("clamav.unreachable", host=host, error=type(exc).__name__)
        return "skipped"
    except Exception as exc:
        log.warning("clamav.failed", host=host, error=type(exc).__name__)
        return "error"


async def _instream(host: str, data: bytes) -> AvStatus:
    reader, writer = await asyncio.open_connection(host, CLAMD_PORT)
    try:
        writer.write(b"zINSTREAM\0")
        await writer.drain()
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + CHUNK]
            offset += len(chunk)
            writer.write(struct.pack("!I", len(chunk)))
            writer.write(chunk)
            await writer.drain()
        writer.write(struct.pack("!I", 0))
        await writer.drain()
        raw = await reader.read(4096)
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    text = raw.decode("latin-1", errors="replace").strip()
    if "OK" in text and "FOUND" not in text:
        return "clean"
    if "FOUND" in text:
        return "infected"
    log.warning("clamav.unexpected_reply", reply=text[:120])
    return "error"
