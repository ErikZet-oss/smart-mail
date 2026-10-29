"""Guards for AI reply suggestions (AI_ASSISTANT §9) — code, not prompts. Phase 2c: the checks that apply without
Money. Every check is a dict `{id, level, params}`; level `blocking` stops approve, `warning` is shown on the card."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Literal

Level = Literal["ok", "warning", "blocking"]

PLACEHOLDER = re.compile(r"\[\[\s*DOPLNI[TŤ][^\]]*\]\]", re.I)
# Numbers worth checking: document numbers, prices, dates, quantities (3+ characters with a digit).
_NUMBER = re.compile(r"(?<![\w])\d[\d.,/:-]*\d(?![\w])")
_ATTACHMENT_WORDS = re.compile(r"v\s+prílohe|v\s+příloze|prikladám|přikládám|attached|enclosed|im\s+anhang|anbei", re.I)
SECURITY_PREFIX = "security_"


def check(check_id: str, level: Level, **params: Any) -> dict[str, Any]:
    return {"id": check_id, "level": level, "params": params}


def _norm_number(value: str) -> str:
    return re.sub(r"[\s.,/:-]", "", value)


def unverified_numbers(body: str, context: str) -> list[str]:
    """Numbers in the draft that appear nowhere in the context the model saw (number/fact check)."""
    known = {_norm_number(n) for n in _NUMBER.findall(context)}
    out: list[str] = []
    for raw in _NUMBER.findall(PLACEHOLDER.sub(" ", body)):
        if len(_norm_number(raw)) < 3:
            continue  # "M8", "2 ks" — too short to be a document number, price or date
        if _norm_number(raw) not in known and raw not in out:
            out.append(raw)
    return out


def reply_checks(
    *,
    body: str,
    context: str,
    recipient: str | None,
    recipient_known: bool,
    internal_domains: Iterable[str],
    security_notes: Iterable[str],
    expected_language: str | None,
    proposal_language: str | None,
    has_attachments: bool = False,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    placeholders = [m.group(0) for m in PLACEHOLDER.finditer(body)]
    if placeholders:
        checks.append(check("placeholder", "blocking", items=placeholders[:10]))
    if not body.strip():
        checks.append(check("empty_body", "blocking"))
    numbers = unverified_numbers(body, context)
    if numbers:
        checks.append(check("unverified_number", "blocking", numbers=numbers[:10]))
    if not recipient or "@" not in recipient:
        checks.append(check("no_recipient", "blocking"))
    else:
        domain = recipient.rsplit("@", 1)[-1].lower()
        if domain not in {d.lower() for d in internal_domains} and not recipient_known:
            checks.append(check("new_recipient", "warning", address=recipient))
    for note in sorted({n for n in security_notes if n.startswith(SECURITY_PREFIX)}):
        checks.append(check(note, "warning"))
    if _ATTACHMENT_WORDS.search(body) and not has_attachments:
        checks.append(check("attachment_missing", "warning"))
    if expected_language and proposal_language and expected_language not in {"other", proposal_language}:
        checks.append(check("language_mismatch", "warning", expected=expected_language, got=proposal_language))
    return checks


def has_blocking(checks: Iterable[dict[str, Any]]) -> bool:
    return any(c.get("level") == "blocking" for c in checks)
