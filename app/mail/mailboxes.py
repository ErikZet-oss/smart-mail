"""Which mailboxes a login may open (CLAUDE.md §4 mailboxes + mailbox_access, PRODUCT_SPEC §2.0).

Until Settings › Schránky (Phase 1f) every login gets exactly its own mailbox, created on the first successful
IMAP login on the login server; the login's stored password (DECISIONS D27) is the sync credential.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Account, AccountKind, Branch
from app.core.config import Settings
from app.mail.models import Mailbox, MailboxAccess


async def ensure_own_mailbox(db: AsyncSession, account: Account, settings: Settings) -> Mailbox:
    """Called after IMAP accepted the password (the password is stored on the account just before)."""
    mailbox = (await db.execute(select(Mailbox).where(Mailbox.email == account.email))).scalar_one_or_none()
    if mailbox is None:
        # AI off until an admin enables it (sets ai_enabled_at); test/non-prod never auto-enables (Phase 2a D).
        mailbox = Mailbox(
            email=account.email,
            imap_host=settings.imap_login_host,
            imap_port=settings.imap_login_port,
            imap_security=settings.imap_login_security,
            # Outbound SMTP follows the same login host defaults until Settings › Schránky overrides (#20).
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            smtp_security=settings.smtp_security,
            credential_account_id=account.id,
            sync_state="new",
            ai_enabled=False,
            ai_enabled_at=None,
        )
        db.add(mailbox)
        await db.flush()
    else:
        mailbox.credential_account_id = account.id
        if mailbox.sync_state == "auth_failed":
            mailbox.sync_state, mailbox.sync_error = "new", None  # fresh password from this login
        # Fill SMTP from env when an older row has none (pilot mailboxes created before #20).
        if not mailbox.smtp_host:
            mailbox.smtp_host = settings.smtp_host
            mailbox.smtp_port = settings.smtp_port
            mailbox.smtp_security = settings.smtp_security
    access = (
        await db.execute(
            select(MailboxAccess).where(MailboxAccess.account_id == account.id, MailboxAccess.mailbox_id == mailbox.id)
        )
    ).scalar_one_or_none()
    if access is None:
        db.add(MailboxAccess(account_id=account.id, mailbox_id=mailbox.id, can_send=True))
    if account.kind == AccountKind.branch and account.branch_id is not None:
        branch = await db.get(Branch, account.branch_id)
        if branch is not None and branch.mailbox_id is None:
            branch.mailbox_id = mailbox.id
    await db.flush()
    return mailbox


async def accessible_mailboxes(db: AsyncSession, account_id: uuid.UUID) -> list[Mailbox]:
    rows = await db.execute(
        select(Mailbox)
        .join(MailboxAccess, MailboxAccess.mailbox_id == Mailbox.id)
        .where(MailboxAccess.account_id == account_id)
        .order_by(Mailbox.email)
    )
    return list(rows.scalars())


async def accessible_mailbox(db: AsyncSession, account: Account, ref: str) -> Mailbox | None:
    """`ref` = mailbox id, or `default` (route `/mail/default/inbox`) = the login's own mailbox, else the first."""
    mailboxes = await accessible_mailboxes(db, account.id)
    if ref == "default":
        own = next((m for m in mailboxes if m.email == account.email), None)
        return own or (mailboxes[0] if mailboxes else None)
    try:
        wanted = uuid.UUID(ref)
    except ValueError:
        return None
    return next((m for m in mailboxes if m.id == wanted), None)
