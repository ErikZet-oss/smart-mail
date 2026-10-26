"""Render branch / identity signatures with the active person (PRODUCT_SPEC §2.0, DECISIONS D10/D22)."""

from __future__ import annotations

import html
import re

from app.auth.models import Branch, Person
from app.mail.compose_models import Identity
from app.mail.sanitize import sanitize_html

_VAR = re.compile(r"\{(meno|priezvisko|funkcia|telefon|mobil|email|pobocka|adresa|firma)\}", re.I)


def _values(person: Person | None, branch: Branch | None, email: str) -> dict[str, str]:
    return {
        "meno": person.first_name if person else "",
        "priezvisko": person.last_name if person else "",
        "funkcia": (person.function or "") if person else "",
        "telefon": (person.phone or "") if person else "",
        "mobil": (person.mobile or "") if person else "",
        "email": email,
        "pobocka": branch.name if branch else "",
        "adresa": (branch.address or "") if branch else "",
        "firma": "Smart s.r.o.",
    }


def fill_variables(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1).lower()
        return html.escape(values.get(key, ""))

    return _VAR.sub(repl, template)


def render_signature(
    *,
    person: Person | None,
    branch: Branch | None,
    identity: Identity | None,
    email: str,
    language: str = "sk",
    override_html: str | None = None,
) -> str:
    """HTML signature block for the draft (sanitised, ≤ 64 kB)."""
    if override_html is not None:
        return sanitize_html(override_html[:65_536])
    values = _values(person, branch, email)
    lang = language.lower()[:2] or "sk"
    template = ""
    if branch and isinstance(branch.signature_template_html, dict):
        template = branch.signature_template_html.get(lang) or branch.signature_template_html.get("sk") or ""
    if not template and identity and isinstance(identity.signature_html, dict):
        template = identity.signature_html.get(lang) or identity.signature_html.get("sk") or ""
    if not template and person:
        # minimal fallback until SETTINGS 11c fills the branch template
        parts = [
            f"<p><strong>{html.escape(person.full_name)}</strong>",
            f"<br/>{html.escape(person.function)}" if person.function else "",
            f"<br/>{html.escape(branch.name)}" if branch else "",
            f"<br/>{html.escape(email)}</p>",
        ]
        template = "".join(parts)
    filled = fill_variables(template, values)
    return sanitize_html(filled[:65_536])


def html_to_text(html_body: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", html_body)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def default_branch_template() -> dict[str, str]:
    """Fictional starter template used when a branch is created in tests / seed."""
    sk = (
        "<p><strong>{meno} {priezvisko}</strong><br/>{funkcia}<br/>"
        "Smart s.r.o. – {pobocka}<br/>{telefon}<br/>"
        '<a href="mailto:{email}">{email}</a></p>'
    )
    return {"sk": sk, "cs": sk, "en": sk, "de": sk}
