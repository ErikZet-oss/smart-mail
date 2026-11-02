"""Phase 4a: supplier documents from mail — messages classified `supplier_document` with a PDF / XML attachment.

Runs after classification in the mailbox AI job; only mail eligible for AI (private folders, Koncepty, Kôš … are
never read — D21), only attachments not flagged by ClamAV, only when FEATURE_MONEY is on. Idempotent per
(message, file hash). Read-only: nothing is written to Money.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import Classification
from app.ai.pipeline import message_eligible_for_ai
from app.ai.provider import LLMProvider, get_llm_provider
from app.core.config import Settings
from app.mail import storage
from app.mail.models import Attachment, FolderMeta, Mailbox, Message
from app.purchasing.models import SupplierDocument
from app.purchasing.service import MAX_BYTES, DocumentRejected, Source, file_kind, ingest

log = structlog.get_logger(__name__)
CATEGORY = "supplier_document"
MAX_PER_RUN = 10
FILE_SUFFIXES = (".pdf", ".xml", ".isdoc", ".isdocx")


async def intake_supplier_documents(
    db: AsyncSession, mailbox: Mailbox, settings: Settings, provider: LLMProvider | None = None
) -> dict[str, int]:
    """The caller commits."""
    stats = {"messages": 0, "documents": 0, "skipped": 0}
    if not settings.feature_money or not mailbox.ai_enabled:
        return stats
    done = select(SupplierDocument.id).where(SupplierDocument.message_id == Message.id).exists()
    rows = await db.execute(
        select(Message, FolderMeta)
        .join(FolderMeta, FolderMeta.id == Message.folder_id)
        .join(Classification, Classification.message_id == Message.id)
        .where(
            Message.mailbox_id == mailbox.id,
            Classification.status == "done",
            Classification.category == CATEGORY,
            ~done,
        )
        .order_by(Message.received_at.desc())
        .limit(MAX_PER_RUN)
    )
    provider = provider or get_llm_provider(settings)
    for message, folder in rows.all():
        if not message_eligible_for_ai(mailbox, folder, message):
            continue
        stats["messages"] += 1
        attachments = await db.scalars(
            select(Attachment).where(
                Attachment.message_id == message.id,
                Attachment.is_inline.is_(False),
                Attachment.av_status != "infected",
                Attachment.size <= MAX_BYTES,
            )
        )
        for att in attachments:
            if not (att.filename or "").lower().endswith(FILE_SUFFIXES) and att.content_type not in (
                "application/pdf",
                "application/xml",
                "text/xml",
            ):
                continue
            data = storage.get_bytes(settings, att.storage_key)
            if data is None:
                stats["skipped"] += 1
                continue
            try:
                file_kind(data, att.filename, att.content_type)
                await ingest(
                    db,
                    settings,
                    provider,
                    Source(
                        data=data,
                        filename=att.filename,
                        content_type=att.content_type,
                        source="mail",
                        message=message,
                        attachment_id=att.id,
                    ),
                )
                stats["documents"] += 1
            except DocumentRejected:
                stats["skipped"] += 1
    log.info("purchasing.intake", mailbox_id=str(mailbox.id), **stats)
    return stats
