"""Login accounts managed by the admin (Settings 10/11, CLI): create, convert to a branch login, guard the last admin.

Used by `app.api.settings` and `app.cli`, so both follow the same rules (issue #33).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch, Person, PersonBranch, Role
from app.auth.persons import own_login_person_ids
from app.auth.sessions import RevokeReason, revoke_account_sessions


class AccountRuleError(Exception):
    """A requested change breaks a rule; `code` is the API error code, `status` the HTTP status."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


async def active_admin_exists(db: AsyncSession) -> bool:
    """True when at least one active login can still sign in as an active admin person: a personal account of an
    admin, or a branch account whose branch (or a covered branch) has an active admin person."""
    personal = (
        select(Account.id)
        .join(Person, Person.id == Account.person_id)
        .where(
            Account.active.is_(True),
            Account.kind == AccountKind.personal,
            Person.active.is_(True),
            Person.role == Role.admin,
        )
    )
    covering = select(PersonBranch.person_id).where(PersonBranch.branch_id == Account.branch_id)
    branch_admin = exists(
        select(Person.id).where(
            Person.active.is_(True),
            Person.role == Role.admin,
            or_(Person.branch_id == Account.branch_id, Person.id.in_(covering)),
            Person.id.not_in(own_login_person_ids()),  # not in the branch picker (#71)
        )
    )
    branch = select(Account.id).where(
        Account.active.is_(True), Account.kind == AccountKind.branch, Account.branch_id.is_not(None), branch_admin
    )
    return bool(await db.scalar(select(exists(personal.union(branch).subquery().select()))))


async def ensure_admin_remains(db: AsyncSession) -> None:
    """Call after applying (and before committing) a change: refuses with 409 `last_admin` if no admin can sign in."""
    await db.flush()
    if not await active_admin_exists(db):
        raise AccountRuleError(409, "last_admin")


async def convert_to_branch(db: AsyncSession, account: Account, branch: Branch, *, now: datetime | None = None) -> int:
    """Turn a login into the branch login of `branch` ("Zmeniť na prihlásenie pobočky", "Prepojiť prihlásenie
    s pobočkou"). The placeholder person of an auto-provisioned personal account is deactivated, never deleted
    (history keeps the name). Sessions of the account are revoked, so the next login shows "Kto ste?".
    Returns the number of revoked sessions."""
    placeholder = await db.get(Person, account.person_id) if account.person_id else None
    if placeholder is not None:  # its branch, if any, was only for the signature (#71)
        placeholder.active = False
    account.kind = AccountKind.branch
    account.branch_id = branch.id
    account.person_id = None
    return await revoke_account_sessions(db, account.id, RevokeReason.account_changed, now=now or datetime.now(UTC))


async def create_account(
    db: AsyncSession,
    email: str,
    *,
    kind: AccountKind,
    branch_id: uuid.UUID | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    role: Role = Role.sales,
) -> Account:
    email = email.strip().lower()
    if await db.scalar(select(Account.id).where(Account.email == email)):
        raise AccountRuleError(409, "account_exists")
    if kind == AccountKind.branch:
        if branch_id is None or await db.get(Branch, branch_id) is None:
            raise AccountRuleError(422, "branch_required")
        account = Account(email=email, kind=kind, branch_id=branch_id)
    else:
        first, last = (first_name or "").strip(), (last_name or "").strip()
        if not first or not last:
            raise AccountRuleError(422, "name_required")
        person = Person(first_name=first[:50], last_name=last[:50], role=role)
        db.add(person)
        await db.flush()
        account = Account(email=email, kind=kind, person_id=person.id)
    db.add(account)
    await db.flush()
    return account
