"""Shared fixtures for tests that need PostgreSQL and Redis (auth, sessions, audit).

Locally the tests are skipped when the services are not running; CI sets REQUIRE_SERVICES=1 so they fail instead.
The test database is wiped and migrated once per run; tables and the Redis test db are emptied before each test.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import asyncpg
import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch, Person, Role
from app.core.config import Settings
from app.mail.imap import LoginResult
from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://smartmail:smartmail@localhost:5432/smartmail_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")
TABLES = (
    "attachments, messages, threads, user_settings, folders_meta, mailbox_access, mailboxes, "
    "device_person_memory, sessions, accounts, person_branches, persons, branches"
)


async def _services_up() -> str | None:
    try:
        conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""), timeout=3)
        await conn.close()
    except Exception as exc:
        return f"PostgreSQL not reachable ({type(exc).__name__})"
    try:
        redis = Redis.from_url(TEST_REDIS_URL)
        await redis.ping()
        await redis.aclose()
    except Exception as exc:
        return f"Redis not reachable ({type(exc).__name__})"
    return None


async def _reset_schema() -> None:
    conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
    try:
        await conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def migrated() -> str:
    problem = asyncio.run(_services_up())
    if problem:
        if os.environ.get("REQUIRE_SERVICES") == "1":
            pytest.fail(problem)
        pytest.skip(problem)
    asyncio.run(_reset_schema())
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    return TEST_DATABASE_URL


@pytest.fixture
def settings(migrated: str) -> Settings:
    return Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url=migrated,
        redis_url=TEST_REDIS_URL,
        mail_sync_enabled=False,  # tests that sync use the local test IMAP server (tests/integration)
    )


@dataclass
class FakeMailServer:
    """Stands in for the IMAP server: known mailbox passwords, or 'down'."""

    passwords: dict[str, str] = field(default_factory=dict)
    down: bool = False
    calls: int = 0

    async def verify(self, email: str, password: str) -> LoginResult:
        self.calls += 1
        if self.down:
            return LoginResult.server_unavailable
        if self.passwords.get(email) == password:
            return LoginResult.ok
        return LoginResult.invalid_credentials


@pytest.fixture
def mail_server() -> FakeMailServer:
    return FakeMailServer()


@pytest.fixture
async def app(settings: Settings, mail_server: FakeMailServer) -> AsyncIterator[FastAPI]:
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        application.state.authenticator = mail_server
        await application.state.redis.flushdb()
        async with application.state.engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
            # the append-only trigger also blocks TRUNCATE; only the test superuser may bypass it like this
            await conn.execute(text("SET LOCAL session_replication_role = replica"))
            await conn.execute(text("TRUNCATE audit_log"))
        yield application


@pytest.fixture
async def db(app: FastAPI) -> AsyncIterator[AsyncSession]:
    async with app.state.sessionmaker() as session:
        yield session


class Client(httpx.AsyncClient):
    """Browser-like client: keeps cookies and sends the CSRF header from the `sm_csrf` cookie."""

    async def csrf(self) -> None:
        if "sm_csrf" not in self.cookies:
            (await self.get("/api/auth/csrf")).raise_for_status()

    async def send_json(self, method: str, url: str, json: object | None = None) -> httpx.Response:
        await self.csrf()
        return await self.request(method, url, json=json, headers={"X-CSRF-Token": self.cookies["sm_csrf"]})

    async def login(self, email: str, password: str, remember: bool = False) -> httpx.Response:
        return await self.send_json(
            "POST", "/api/auth/login", {"email": email, "password": password, "remember": remember}
        )


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[Client]:
    async with Client(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def new_client(app: FastAPI) -> Callable[[], Client]:
    """Factory for a second browser (another device)."""

    def make() -> Client:
        return Client(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return make


async def make_personal(
    db: AsyncSession, email: str = "jana@smartsro.sk", role: Role = Role.sales, **account: object
) -> Account:
    person = Person(first_name="Jana", last_name="Testová", role=role)
    db.add(person)
    await db.flush()
    acc = Account(email=email, kind=AccountKind.personal, person_id=person.id, **account)
    db.add(acc)
    await db.commit()
    return acc


async def make_branch(
    db: AsyncSession, name: str = "Nitra", people: int = 2, **branch: object
) -> tuple[Branch, Account]:
    b = Branch(name=name, **branch)
    db.add(b)
    await db.flush()
    for i in range(people):
        db.add(Person(branch_id=b.id, first_name=f"Osoba{i}", last_name="Pobočka", role=Role.sales))
    acc = Account(email=f"{name.lower()}@smartsro.sk", kind=AccountKind.branch, branch_id=b.id)
    db.add(acc)
    await db.commit()
    return b, acc
