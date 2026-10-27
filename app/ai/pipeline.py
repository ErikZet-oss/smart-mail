"""Pipeline gates for Phase 2a — history, D21 folders, AV, Message-ID idempotency (no classify UI yet)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.mail.models import Attachment, FolderMeta, Mailbox, Message

# SPECIAL-USE folders excluded from the AI pipeline (DECISIONS D21 / AI_ASSISTANT §2).
_EXCLUDED_SPECIAL = frozenset({"drafts", "sent", "trash", "junk"})


class RecordingLLM:
    """Test double: counts would-be LLM calls without a network."""

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, *_args: object, **_kwargs: object) -> None:
        self.call_count += 1
        raise AssertionError("RecordingLLM.complete must not be reached for historical mail")


@dataclass(frozen=True, slots=True)
class BackfillEstimate:
    message_count: int
    limit: int
    will_process: int
    estimated_usd: Decimal
    summary_sk: str


def folder_eligible_for_ai(folder: FolderMeta) -> bool:
    if not folder.subscribed or not folder.selectable:
        return False
    if folder.private:
        return False
    if folder.special_use in _EXCLUDED_SPECIAL:
        return False
    return True


def message_eligible_for_ai(mailbox: Mailbox, folder: FolderMeta, message: Message) -> bool:
    if not mailbox.ai_enabled or mailbox.ai_enabled_at is None:
        return False
    if not folder_eligible_for_ai(folder):
        return False
    received = message.received_at
    if received is None:
        return False
    # timezone-aware compare; treat naive as already UTC only in tests that set tzinfo
    enabled_at = mailbox.ai_enabled_at
    if received.tzinfo is None and enabled_at.tzinfo is not None:
        return False
    return received >= enabled_at


def attachments_eligible_for_ai(attachments: list[Attachment]) -> bool:
    """AI may touch an attachment only when av_status=clean (AI_ASSISTANT §2 Phase 2 rule)."""
    for att in attachments:
        if att.av_status != "clean":
            return False
    return True


def select_new_messages_for_ai(mailbox: Mailbox, folder: FolderMeta, messages: list[Message]) -> list[Message]:
    """Messages that may enter the pipeline — never history before ai_enabled_at."""
    return [m for m in messages if message_eligible_for_ai(mailbox, folder, m)]


def normalize_message_id_header(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if value.startswith("<") and value.endswith(">"):
        value = value[1:-1].strip()
    return value or None


def estimate_backfill(
    *,
    message_count: int,
    limit: int,
    classify_usd_per_1k: Decimal,
) -> BackfillEstimate:
    """Manual backfill only: operator sees count, cost estimate, and hard limit."""
    if limit < 0:
        raise ValueError("limit must be >= 0")
    if message_count < 0:
        raise ValueError("message_count must be >= 0")
    will = min(message_count, limit)
    estimated = (Decimal(will) / Decimal(1000)) * classify_usd_per_1k
    estimated = estimated.quantize(Decimal("0.01"))
    summary_sk = (
        f"Spätné spracovanie: {will} z {message_count} správ (limit {limit}), "
        f"odhad ~{estimated} USD (len klasifikácia)."
    )
    return BackfillEstimate(
        message_count=message_count,
        limit=limit,
        will_process=will,
        estimated_usd=estimated,
        summary_sk=summary_sk,
    )


class ShadowModeStore(Protocol):
    def ai_shadow_mode(self) -> bool: ...


def is_shadow_mode(flag_enabled: bool | None) -> bool:
    return bool(flag_enabled)
