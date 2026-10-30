"""Deterministic triage rules (AI_ASSISTANT §2 step 3) — run before the LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Common carrier / tracking notification domains (not exhaustive).
_CARRIER_DOMAINS = frozenset(
    {
        "dhl.com",
        "dhl.de",
        "dhl.sk",
        "dpd.com",
        "dpd.sk",
        "dpd.cz",
        "ups.com",
        "fedex.com",
        "gls-group.eu",
        "gls-czech.com",
        "gls-slovakia.sk",
        "packeta.com",
        "zasilkovna.cz",
        "posta.sk",
        "slovenskaposta.sk",
        "tracking.",
    }
)

_ISDOC_NAMES = re.compile(r"\.(isdoc|isdocx)$", re.I)
_UBL_NAMES = re.compile(r"(ubl|factur[-_]?x|invoice).*\.(xml|pdf)$", re.I)
_SUPPLIER_PDF = re.compile(r"(fakt[uú]r|invoice|dodac[ií]|delivery[-_ ]?note|lieferschein)", re.I)
_LIST_UNSUB = re.compile(r"list-unsubscribe", re.I)
# Pilot 2026-10-30: „Faktura E3/2026/19608“ from a supplier with E3_126_19608.pdf + .csv was classified as an invoice
# request twice. A NEW external mail whose subject starts with a document word and carries a document attachment is a
# supplier document; replies/forwards („Re:“ — a customer asking about our invoice) are left to the model.
_SUPPLIER_SUBJECT = re.compile(
    r"^\s*(fakt[uú]ra|faktury|invoice|rechnung|dobropis|credit\s*note|dodac[ií]\s*list|delivery\s*note|lieferschein)\b",
    re.I,
)
_REPLY_PREFIX = re.compile(r"^\s*(re|odp|aw|fw|fwd|wg|tr)\s*:", re.I)
_DOCUMENT_ATTACHMENT = re.compile(r"\.(pdf|isdoc|isdocx|xml|csv)$", re.I)


@dataclass(frozen=True, slots=True)
class RuleHit:
    category: str
    decisive: bool
    rule_id: str
    priority: str = "normal"
    notes: tuple[str, ...] = ()


def _domain(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    return email.rsplit("@", 1)[-1].strip().lower()


def _is_carrier(domain: str) -> bool:
    if not domain:
        return False
    if domain in _CARRIER_DOMAINS:
        return True
    return any(
        domain.endswith(d) if d.startswith(".") else domain == d or domain.endswith("." + d) for d in _CARRIER_DOMAINS
    )


def apply_rules(
    *,
    from_email: str | None,
    subject: str | None,
    headers_text: str | None,
    attachment_names: list[str],
    auth_results: dict[str, Any] | None,
    internal_domains: list[str],
) -> RuleHit | None:
    """Return the first decisive (or spam-candidate) rule hit, else None."""
    subj = subject or ""
    hdr = headers_text or ""
    domain = _domain(from_email)
    internal = {d.lower() for d in internal_domains}

    if _LIST_UNSUB.search(hdr) or "list-unsubscribe:" in hdr.lower():
        return RuleHit(category="newsletter", decisive=True, rule_id="list_unsubscribe")

    if _is_carrier(domain) or re.search(r"\b(tracking|zásielk|zásilka|tracking number|tracking-nr)\b", subj, re.I):
        return RuleHit(category="shipping", decisive=True, rule_id="carrier")

    if domain and domain in internal:
        return RuleHit(category="internal", decisive=True, rule_id="internal_domain")

    pdf_hint: RuleHit | None = None
    for name in attachment_names:
        if _ISDOC_NAMES.search(name) or _UBL_NAMES.search(name):
            return RuleHit(category="supplier_document", decisive=True, rule_id="isdoc_ubl")
        if pdf_hint is None and name.lower().endswith(".pdf") and _SUPPLIER_PDF.search(name):
            # Needs LLM confirmation per AI_ASSISTANT — not decisive
            pdf_hint = RuleHit(category="supplier_document", decisive=False, rule_id="supplier_pdf_name")

    dmarc = (auth_results or {}).get("dmarc", "").lower()
    if dmarc in {"fail", "softfail"}:
        return RuleHit(
            category="spam",
            decisive=False,
            rule_id="dmarc_fail",
            priority="urgent",
            notes=("security_dmarc_fail",),
        )

    # after the DMARC check: a spoofed „Faktura“ must still be flagged, never fast-tracked as a supplier document
    if (
        _SUPPLIER_SUBJECT.search(subj)
        and not _REPLY_PREFIX.search(subj)
        and any(_DOCUMENT_ATTACHMENT.search(n) for n in attachment_names)
    ):
        return RuleHit(category="supplier_document", decisive=True, rule_id="supplier_subject_attachment")

    return pdf_hint
