"""Phase 3d: build the reply draft with the original Money invoice PDFs (used by approve and by „Poslať“)."""

from __future__ import annotations

import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Branch, Person
from app.core.config import Settings
from app.mail import storage
from app.mail.compose import create_draft, text_to_html
from app.mail.compose_models import ComposeAttachment, ComposeDraft
from app.mail.models import Mailbox, Message
from app.money.bridge_client import BridgeClient
from app.money.invoice_attach import Evaluation, load_reports, pick_report, storage_prefix

FILE_PREFIX = {"invoice": "Faktura", "proforma": "Zalohova_faktura"}


class InvoiceDraftError(Exception):
    def __init__(self, code: str, number: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.number = number


def pdf_filename(kind: str, number: str) -> str:
    return f"{FILE_PREFIX.get(kind, 'Faktura')}_{re.sub(r'[^A-Za-z0-9_-]+', '-', number).strip('-')}.pdf"


async def build_invoice_draft(
    db: AsyncSession,
    settings: Settings,
    bridge: BridgeClient,
    *,
    mailbox: Mailbox,
    message: Message,
    account_id: uuid.UUID,
    person: Person | None,
    branch: Branch | None,
    evaluation: Evaluation,
    body: str,
    language: str | None,
) -> ComposeDraft:
    """Reply draft to the checked recipient only, with every invoice PDF from Money. The caller commits.
    Raises `InvoiceDraftError` (blocked / pdf missing) or `BridgeUnavailable`."""
    if evaluation.blocked or evaluation.company_money_id is None:
        raise InvoiceDraftError("suggestion_blocked")
    reports = await load_reports(db)
    pdfs: list[tuple[str, bytes]] = []
    for inv in evaluation.invoices:
        report_id = pick_report(reports, inv.kind, language)
        if report_id is None:
            raise InvoiceDraftError("report_not_configured", inv.number)
        data = await bridge.invoice_pdf(inv.kind, inv.id, report_id)
        if not data:
            raise InvoiceDraftError("pdf_missing", inv.number)
        pdfs.append((pdf_filename(inv.kind, inv.number), data))
    draft = await create_draft(
        db,
        settings,
        mailbox=mailbox,
        account_id=account_id,
        person=person,
        branch=branch,
        mode="reply",
        source=message,
        user_html=text_to_html(body),
    )
    draft.to_addrs = [{"name": None, "email": evaluation.email}]  # only the checked recipient
    draft.cc_addrs = []
    prefix = storage_prefix(draft.id, evaluation.company_money_id)
    for filename, data in pdfs:
        key, digest = storage.put_bytes(settings, data, prefix=prefix)
        db.add(
            ComposeAttachment(
                draft_id=draft.id,
                filename=filename,
                content_type="application/pdf",
                size=len(data),
                storage_key=key,
                sha256=digest,
                av_status="clean",  # Money's own report, fetched by the bridge
                is_inline=False,
            )
        )
    await db.flush()
    return draft
