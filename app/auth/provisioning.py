"""Accounts created on the first successful mailbox login and the stored mailbox password (DECISIONS D25, D27)."""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Person, Role
from app.auth.security import encrypt, fingerprint_matches, password_fingerprint
from app.core.config import Settings

_NAME_SPLIT = re.compile(r"[._\-+]+")


def name_from_address(email: str) -> tuple[str, str]:
    """`peter.hudak@…` → ("Peter", "Hudak"). Only a placeholder until an admin edits the person (SETTINGS 11)."""
    parts = [p for p in _NAME_SPLIT.split(email.partition("@")[0]) if p]
    if not parts:
        return email[:80], ""
    return parts[0].capitalize()[:80], " ".join(p.capitalize() for p in parts[1:])[:80]


async def provision_account(db: AsyncSession, email: str, settings: Settings) -> Account:
    """Personal account + person for an internal address that just passed IMAP LOGIN. Viewer (read-only) until an
    admin assigns a role; addresses in ADMIN_EMAILS start as admin."""
    first, last = name_from_address(email)
    role = Role.admin if email in settings.admin_email_list else Role.viewer
    person = Person(first_name=first, last_name=last, role=role)
    db.add(person)
    await db.flush()
    account = Account(email=email, kind=AccountKind.personal, person_id=person.id)
    db.add(account)
    await db.flush()
    return account


def remember_mailbox_password(account: Account, password: str, settings: Settings, *, now: datetime) -> bool:
    """Called only after the IMAP server accepted `password`. Returns True when the password differs from the last
    one (= changed on the mail server); the fingerprint and the encrypted copy are then overwritten at once."""
    changed = account.password_fingerprint is not None and not fingerprint_matches(
        password, account.password_fingerprint
    )
    if changed or account.password_fingerprint is None or account.mailbox_password_enc is None:
        account.password_fingerprint = password_fingerprint(password)
        account.mailbox_password_enc = encrypt(settings, password)
        account.mailbox_password_set_at = now
    return changed
