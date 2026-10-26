"""Message threading (CLAUDE.md §5): References / In-Reply-To, else normalized subject + participants (30 days)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.mail.threading import ThreadKey, normalize_subject, thread_key_for


def test_threading_1d_normalize_subject_strips_re_fw_prefixes() -> None:
    assert normalize_subject("Re: Objednávka PO-1") == normalize_subject("Objednávka PO-1")
    assert normalize_subject("FW: Re: AW: Dopyt") == normalize_subject("Dopyt")
    assert normalize_subject("  Re:   Cenová ponuka  ") == normalize_subject("Cenová ponuka")


def test_threading_1d_prefer_in_reply_to_and_references() -> None:
    root = thread_key_for(
        message_id="<root@x>",
        in_reply_to=None,
        references=None,
        subject="Hello",
        from_email="a@x.example",
        to_emails=["b@x.example"],
        sent_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    a = thread_key_for(
        message_id="<a@x>",
        in_reply_to="<root@x>",
        references="<root@x> <mid@x>",
        subject="Re: Hello",
        from_email="a@x.example",
        to_emails=["b@x.example"],
        sent_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    b = thread_key_for(
        message_id="<b@x>",
        in_reply_to="<root@x>",
        references=None,
        subject="Re: Hello",
        from_email="b@x.example",
        to_emails=["a@x.example"],
        sent_at=datetime(2026, 10, 2, tzinfo=UTC),
    )
    assert root.kind == "msgid"
    assert root.value == "<root@x>"
    assert a == root == b


def test_threading_1d_fallback_subject_participants_within_30_days() -> None:
    t0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    first = thread_key_for(
        message_id=None,
        in_reply_to=None,
        references=None,
        subject="Dopyt: skrutky",
        from_email="novak@abc.example",
        to_emails=["pilot@smartmail.test"],
        sent_at=t0,
    )
    same = thread_key_for(
        message_id=None,
        in_reply_to=None,
        references=None,
        subject="Re: Dopyt: skrutky",
        from_email="pilot@smartmail.test",
        to_emails=["novak@abc.example"],
        sent_at=t0 + timedelta(days=5),
    )
    other = thread_key_for(
        message_id=None,
        in_reply_to=None,
        references=None,
        subject="Dopyt: skrutky",
        from_email="other@z.example",
        to_emails=["pilot@smartmail.test"],
        sent_at=t0,
    )
    assert first.kind == "fallback"
    assert first == same
    assert first != other


def test_threading_1d_fallback_key_stable_across_dates() -> None:
    """The 30-day window is enforced when attaching to a stored thread, not by bucketing the key."""
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    a = thread_key_for(
        message_id=None,
        in_reply_to=None,
        references=None,
        subject="Porada",
        from_email="a@x.example",
        to_emails=["b@x.example"],
        sent_at=t0,
    )
    b = thread_key_for(
        message_id=None,
        in_reply_to=None,
        references=None,
        subject="Porada",
        from_email="a@x.example",
        to_emails=["b@x.example"],
        sent_at=t0 + timedelta(days=31),
    )
    assert isinstance(a, ThreadKey)
    assert a.kind == "fallback"
    assert a == b
