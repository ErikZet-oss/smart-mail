"""GitHub #23 — reply/forward flags and APPEND failure (no resend) without a mail server."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import encrypt
from app.core.config import Settings
from app.mail.compose import execute_send
from app.mail.compose_models import ComposeDraft, Identity
from app.mail.flags import FORWARDED_FLAG, apply_local_flag, is_forwarded
from app.mail.imap_append import AppendedMessage
from app.mail.models import FolderMeta, Mailbox, Message
from app.mail.sync import SyncUnavailable
from tests.conftest import make_personal

PASSWORD = "heslo-23"


def test_23_local_flag_marks_answered_and_forwarded() -> None:
    message = Message(mailbox_id=uuid.uuid4(), folder_id=uuid.uuid4(), uid=1, flags=[], answered=False)
    apply_local_flag(message, "\\Answered")
    assert message.answered is True
    assert "\\Answered" in message.flags
    apply_local_flag(message, "\\Answered")
    assert message.flags.count("\\Answered") == 1
    forwarded = Message(mailbox_id=uuid.uuid4(), folder_id=uuid.uuid4(), uid=2, flags=["$Forwarded"])
    assert is_forwarded(forwarded.flags)
    assert not is_forwarded(["\\Seen"])
    assert FORWARDED_FLAG == "$Forwarded"


async def _mailbox(db: AsyncSession, settings: Settings, email: str) -> tuple[Mailbox, Identity, FolderMeta]:
    account = await make_personal(db, email=email, mailbox_password_enc=encrypt(settings, PASSWORD))
    mailbox = Mailbox(
        email=account.email,
        imap_host="localhost",
        imap_port=143,
        imap_security="none",
        credential_account_id=account.id,
    )
    db.add(mailbox)
    await db.flush()
    folder = FolderMeta(mailbox_id=mailbox.id, name="INBOX", special_use="inbox")
    db.add(folder)
    await db.flush()
    identity = Identity(mailbox_id=mailbox.id, display_name="Jana", email=account.email, is_default=True)
    db.add(identity)
    await db.flush()
    sent = FolderMeta(mailbox_id=mailbox.id, name="INBOX.Sent", special_use="sent", delimiter=".")
    db.add(sent)
    await db.commit()
    return mailbox, identity, folder


@pytest.mark.asyncio
async def test_23_reply_stores_answered_and_appends_to_known_sent(db: AsyncSession, settings: Settings) -> None:
    mailbox, identity, folder = await _mailbox(db, settings, "reply23@smartmail.test")
    source = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=7,
        message_id="<src-23@smartmail.test>",
        subject="Otázka",
        from_email="sender@smartmail.test",
        flags=[],
        answered=False,
    )
    db.add(source)
    await db.flush()
    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=mailbox.credential_account_id,
        identity_id=identity.id,
        mode="reply",
        in_reply_to_message_id=source.id,
        to_addrs=[{"email": "sender@smartmail.test"}],
        subject="Re: Otázka",
        body_html="<p>Ahoj</p>",
        body_text="Ahoj",
        status="queued",
    )
    db.add(draft)
    await db.commit()

    with (
        patch("app.mail.compose.send_message", new_callable=AsyncMock) as send,
        patch("app.mail.compose.append_to_sent_async", new_callable=AsyncMock) as append,
        patch("app.mail.compose.sync_mailbox", new_callable=AsyncMock) as sync,
        patch("app.mail.compose.add_flag_async", new_callable=AsyncMock) as flag,
    ):
        append.return_value = AppendedMessage(uid=3, folder="INBOX.Sent")
        result = await execute_send(db, settings, draft.id)

    assert result == "sent"
    send.assert_awaited_once()
    flag.assert_awaited_once()
    assert flag.await_args is not None
    assert flag.await_args.args[-1] == "\\Answered"
    assert append.await_args is not None
    assert append.await_args.kwargs["known_folder"] == "INBOX.Sent"
    sync.assert_awaited_once()
    assert sync.await_args is not None
    assert sync.await_args.kwargs["only_names"] == frozenset({"INBOX.Sent"})
    await db.refresh(source)
    assert source.answered is True
    assert "\\Answered" in source.flags


@pytest.mark.asyncio
async def test_23_forward_stores_forwarded_keyword(db: AsyncSession, settings: Settings) -> None:
    mailbox, identity, folder = await _mailbox(db, settings, "fwd23@smartmail.test")
    source = Message(
        mailbox_id=mailbox.id,
        folder_id=folder.id,
        uid=8,
        message_id="<fwd-23@smartmail.test>",
        subject="Cenník",
        from_email="sender@smartmail.test",
        flags=[],
        answered=False,
    )
    db.add(source)
    await db.flush()
    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=mailbox.credential_account_id,
        identity_id=identity.id,
        mode="forward",
        in_reply_to_message_id=source.id,
        to_addrs=[{"email": "iny@smartmail.test"}],
        subject="Fwd: Cenník",
        body_html="<p>Preposielam</p>",
        body_text="Preposielam",
        status="queued",
    )
    db.add(draft)
    await db.commit()

    with (
        patch("app.mail.compose.send_message", new_callable=AsyncMock),
        patch("app.mail.compose.append_to_sent_async", new_callable=AsyncMock) as append,
        patch("app.mail.compose.sync_mailbox", new_callable=AsyncMock),
        patch("app.mail.compose.add_flag_async", new_callable=AsyncMock) as flag,
    ):
        append.return_value = AppendedMessage(uid=4, folder="INBOX.Sent")
        assert await execute_send(db, settings, draft.id) == "sent"

    assert flag.await_args is not None
    assert flag.await_args.args[-1] == "$Forwarded"
    await db.refresh(source)
    assert source.answered is False
    assert "$Forwarded" in source.flags


@pytest.mark.asyncio
async def test_23_append_failure_does_not_resend(db: AsyncSession, settings: Settings) -> None:
    mailbox, identity, _folder = await _mailbox(db, settings, "append23@smartmail.test")
    draft = ComposeDraft(
        mailbox_id=mailbox.id,
        account_id=mailbox.credential_account_id,
        identity_id=identity.id,
        mode="new",
        to_addrs=[{"email": "sender@smartmail.test"}],
        subject="Nová",
        body_html="<p>Ahoj</p>",
        body_text="Ahoj",
        status="queued",
    )
    db.add(draft)
    await db.commit()

    with (
        patch("app.mail.compose.send_message", new_callable=AsyncMock) as send,
        patch("app.mail.compose.append_to_sent_async", new_callable=AsyncMock) as append,
        patch("app.mail.compose.sync_mailbox", new_callable=AsyncMock) as sync,
    ):
        append.side_effect = SyncUnavailable("append")
        result = await execute_send(db, settings, draft.id)

    assert result == "sent"
    send.assert_awaited_once()
    sync.assert_not_awaited()
    await db.refresh(draft)
    assert draft.status == "sent"
    assert draft.send_error == "append_failed"
