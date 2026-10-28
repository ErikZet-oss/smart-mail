"""Async wrappers around sync sievelib — never block the event loop (pilot issue #18 B1)."""

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sievelib.managesieve import Client as ManageSieveClient

from app.core.config import Settings
from app.mail.models import Mailbox
from app.mail.sieve import (
    SieveError,
    active_script_name,
    connect_sieve,
    get_script,
    put_script,
    sieve_supports_variables,
)

log = structlog.get_logger(__name__)

SIEVE_CONNECT_TIMEOUT_S = 5.0
SIEVE_OVERALL_TIMEOUT_S = 10.0
SIEVE_UNAVAILABLE_CACHE_TTL_S = 600
SIEVE_UNAVAILABLE_CACHE_PREFIX = "sieve:unavailable:"

SIEVE_UNAVAILABLE_MESSAGE_SK = (
    "Filtre a Mimo kancelárie nie sú na tomto serveri dostupné (ManageSieve, port 4190). Pošta funguje normálne."
)

_CONNECT_LOCK = threading.Lock()


def _connect_with_timeout(
    settings: Settings,
    mailbox: Mailbox,
    *,
    username: str,
    password: str,
) -> ManageSieveClient:
    """Like ``connect_sieve`` but ``socket.create_connection`` uses a 5 s timeout.

    Only one TCP attempt is made on black-hole hosts: if connect times out we raise
    ``sieve_unavailable`` immediately (no STARTTLS→cleartext double wait).
    """

    real = socket.create_connection

    def timed_create(
        address: tuple[Any, ...] | str | bytes,
        timeout: float | None = None,
        source_address: tuple[str, int] | None = None,
    ) -> socket.socket:
        # sievelib calls create_connection((host, port)) with no timeout — inject ours.
        effective = SIEVE_CONNECT_TIMEOUT_S if timeout is None else min(float(timeout), SIEVE_CONNECT_TIMEOUT_S)
        return real(address, effective, source_address)  # type: ignore[arg-type]

    with _CONNECT_LOCK:
        socket.create_connection = timed_create  # type: ignore[assignment]
        try:
            return connect_sieve(settings, mailbox, username=username, password=password)
        finally:
            socket.create_connection = real


def cache_key(mailbox_id: UUID) -> str:
    return f"{SIEVE_UNAVAILABLE_CACHE_PREFIX}{mailbox_id}"


async def sieve_marked_unavailable(redis: Redis, mailbox_id: UUID) -> bool:
    try:
        return bool(await redis.get(cache_key(mailbox_id)))
    except Exception:
        return False


async def mark_sieve_unavailable(redis: Redis, mailbox_id: UUID) -> None:
    try:
        await redis.set(cache_key(mailbox_id), b"1", ex=SIEVE_UNAVAILABLE_CACHE_TTL_S)
    except Exception as exc:
        log.warning("sieve.cache_set_failed", error=type(exc).__name__)


async def clear_sieve_unavailable(redis: Redis, mailbox_id: UUID) -> None:
    with contextlib.suppress(Exception):
        await redis.delete(cache_key(mailbox_id))


async def _run_sieve[T](
    redis: Redis,
    mailbox_id: UUID,
    work: Callable[[], T],
) -> T:
    """Run sync ManageSieve work off the event loop with an overall 10 s limit."""
    if await sieve_marked_unavailable(redis, mailbox_id):
        raise SieveError("sieve_unavailable", SIEVE_UNAVAILABLE_MESSAGE_SK)
    try:
        async with asyncio.timeout(SIEVE_OVERALL_TIMEOUT_S):
            return await asyncio.to_thread(work)
    except TimeoutError as exc:
        await mark_sieve_unavailable(redis, mailbox_id)
        raise SieveError("sieve_unavailable", SIEVE_UNAVAILABLE_MESSAGE_SK) from exc
    except SieveError as exc:
        if exc.code == "sieve_unavailable":
            await mark_sieve_unavailable(redis, mailbox_id)
        raise


def _logout_quietly(client: ManageSieveClient) -> None:
    with contextlib.suppress(Exception):
        client.logout()


async def load_active_script(
    *,
    redis: Redis,
    settings: Settings,
    mailbox: Mailbox,
    username: str,
    password: str,
) -> tuple[str, str, bool]:
    """Return ``(script_name, content, supports_variables)``."""

    def work() -> tuple[str, str, bool]:
        client = _connect_with_timeout(settings, mailbox, username=username, password=password)
        try:
            name = active_script_name(client)
            content = get_script(client, name)
            supports = sieve_supports_variables(client)
            return name, content, supports
        finally:
            _logout_quietly(client)

    result = await _run_sieve(redis, mailbox.id, work)
    await clear_sieve_unavailable(redis, mailbox.id)
    return result


async def save_active_script(
    *,
    redis: Redis,
    settings: Settings,
    mailbox: Mailbox,
    username: str,
    password: str,
    content: str,
    script_name: str | None = None,
) -> tuple[str, str, bool]:
    """Upload and activate script. Returns ``(script_name, previous_content, supports_variables)``."""

    def work() -> tuple[str, str, bool]:
        client = _connect_with_timeout(settings, mailbox, username=username, password=password)
        try:
            name = script_name or active_script_name(client)
            previous = get_script(client, name)
            supports = sieve_supports_variables(client)
            put_script(client, name, content, activate=True)
            return name, previous, supports
        finally:
            _logout_quietly(client)

    result = await _run_sieve(redis, mailbox.id, work)
    await clear_sieve_unavailable(redis, mailbox.id)
    return result


async def read_then_write_script(
    *,
    redis: Redis,
    settings: Settings,
    mailbox: Mailbox,
    username: str,
    password: str,
    build: Callable[[str, str, bool], str],
) -> tuple[str, str]:
    """One connection: read active script, ``build(name, content, supports_vars)`` → put.

    Returns ``(script_name, previous_content)``.
    """

    def work() -> tuple[str, str]:
        client = _connect_with_timeout(settings, mailbox, username=username, password=password)
        try:
            name = active_script_name(client)
            previous = get_script(client, name)
            supports = sieve_supports_variables(client)
            new_content = build(name, previous, supports)
            put_script(client, name, new_content, activate=True)
            return name, previous
        finally:
            _logout_quietly(client)

    result = await _run_sieve(redis, mailbox.id, work)
    await clear_sieve_unavailable(redis, mailbox.id)
    return result
