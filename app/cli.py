"""Admin command line until Settings › Používatelia a role / Pobočky a osoby / Systém exist.

    python -m app.cli add-account jana@smartsro.sk --first-name Jana --last-name Nováková --role admin
    python -m app.cli add-account senica@smartsro.sk --branch "Pobočka Senica"
    python -m app.cli add-person "Pobočka Senica" --first-name Peter --last-name Hudák --manager
    python -m app.cli maintenance on --until 2026-10-27T08:00:00+01:00
    python -m app.cli maintenance off

Only accounts registered here (later in Settings 10) can sign in, even with a valid mailbox password.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Account, AccountKind, Branch, Person, Role
from app.core import maintenance
from app.core.audit import audit
from app.core.config import get_settings


async def _branch(db: AsyncSession, name: str) -> Branch:
    branch = (await db.execute(select(Branch).where(Branch.name == name))).scalar_one_or_none()
    if branch is None:
        branch = Branch(name=name)
        db.add(branch)
        await db.flush()
    return branch


async def add_account(db: AsyncSession, args: argparse.Namespace) -> str:
    email = args.email.strip().lower()
    if (await db.execute(select(Account).where(Account.email == email))).scalar_one_or_none():
        return f"account {email} already exists"
    if args.branch:
        branch = await _branch(db, args.branch)
        account = Account(email=email, kind=AccountKind.branch, branch_id=branch.id)
    else:
        if not args.first_name or not args.last_name:
            raise SystemExit("a personal account needs --first-name and --last-name")
        person = Person(first_name=args.first_name, last_name=args.last_name, role=Role(args.role))
        db.add(person)
        await db.flush()
        account = Account(email=email, kind=AccountKind.personal, person_id=person.id)
    db.add(account)
    await db.flush()
    audit(db, "admin.account_created", account_id=account.id, details={"email": email, "via": "cli"})
    return f"created {account.kind} account {email}"


async def add_person(db: AsyncSession, args: argparse.Namespace) -> str:
    branch = await _branch(db, args.branch)
    person = Person(
        branch_id=branch.id,
        first_name=args.first_name,
        last_name=args.last_name,
        function=args.function,
        role=Role(args.role),
        is_manager=args.manager,
    )
    db.add(person)
    await db.flush()
    audit(db, "admin.person_created", object_type="person", object_id=str(person.id), details={"via": "cli"})
    return f"created person {person.full_name} in {branch.name}"


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    acc = sub.add_parser("add-account")
    acc.add_argument("email")
    acc.add_argument("--branch", help="branch mailbox: name of the branch (created if missing)")
    acc.add_argument("--first-name")
    acc.add_argument("--last-name")
    acc.add_argument("--role", default="sales", choices=[r.value for r in Role])
    per = sub.add_parser("add-person")
    per.add_argument("branch")
    per.add_argument("--first-name", required=True)
    per.add_argument("--last-name", required=True)
    per.add_argument("--function")
    per.add_argument("--role", default="sales", choices=[r.value for r in Role])
    per.add_argument("--manager", action="store_true")
    mnt = sub.add_parser("maintenance")
    mnt.add_argument("state", choices=["on", "off"])
    mnt.add_argument("--until", type=datetime.fromisoformat)
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.cmd == "maintenance":
        redis = Redis.from_url(settings.redis_url)
        if args.state == "on":
            await maintenance.start(redis, args.until)
        else:
            await maintenance.stop(redis)
        await redis.aclose()
        print(f"maintenance {args.state}")
        return

    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        message = await (add_account(db, args) if args.cmd == "add-account" else add_person(db, args))
        await db.commit()
    await engine.dispose()
    print(message)


if __name__ == "__main__":
    asyncio.run(main())
