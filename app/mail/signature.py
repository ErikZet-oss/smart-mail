"""Render branch / identity signatures with the active person (PRODUCT_SPEC §2.0, DECISIONS D10/D22).

Branch template variables (SETTINGS 11c): {meno} {priezvisko} {funkcia} {telefon} {mobil}
{email_osobny} {email_pobocky} {pobocka} {adresa_pobocky} {telefon_pobocky} {oteviracie_hodiny}
{web} {fotka} {logo}. Empty values are dropped together with the neighbouring separator.
Colours in the default „Karta“ template are read from design/tokens.css (D24 — no pasted hex).
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

import structlog

from app.auth.models import Branch, Person
from app.mail.compose_models import Identity
from app.mail.sanitize import sanitize_signature_html

SIGNATURE_LANGS = ("sk", "cs", "en", "de")
SIGNATURE_MAX_BYTES = 64 * 1024
log = structlog.get_logger(__name__)

COMPANY_WEB = "www.smartsro.sk"
COMPANY_WEB_URL = "https://www.smartsro.sk/"
LOGO_CID = "logo@smartmail"
PHOTO_CID = "fotka@smartmail"

# Identifiers the branch template may use. Legacy aliases stay so older templates still save.
_VARIABLES = frozenset(
    {
        "meno",
        "priezvisko",
        "funkcia",
        "telefon",
        "mobil",
        "email_osobny",
        "email_pobocky",
        "pobocka",
        "adresa_pobocky",
        "telefon_pobocky",
        "oteviracie_hodiny",
        "web",
        "fotka",
        "logo",
        "email",
        "adresa",
        "firma",
    }
)
_ALIAS = {"adresa": "adresa_pobocky"}
_RAW_HTML = frozenset({"fotka", "logo"})
_VAR = re.compile(r"\{([a-z0-9_]+)\}", re.I)
_EMPTY = "\x00"
_SEP = r"(?:[ \t]*[·|–][ \t]*|[ \t]+-[ \t]+|&nbsp;·&nbsp;|<br\s*/?>)"

_GREET_TEXT = {
    "sk": "S pozdravom",
    "cs": "S pozdravem",
    "en": "Kind regards",
    "de": "Mit freundlichen Grüßen",
}


class SignatureError(Exception):
    def __init__(self, code: str, **extra: object) -> None:
        super().__init__(code)
        self.code = code
        self.extra = extra


def _token(name: str) -> str:
    """Resolve a design token to the value in tokens.css. Falls back to currentColor, never a guessed hex."""
    css_path = Path(__file__).resolve().parents[2] / "design" / "tokens.css"
    if not css_path.is_file():
        # Never silent: a missing file turned the whole Karta dark in the pilot (Docker image without design/).
        log.error("signature.tokens_missing", path=str(css_path))
        return "currentColor"
    text = css_path.read_text(encoding="utf-8")
    match = re.search(rf"--{re.escape(name)}:\s*(#[0-9A-Fa-f]{{3,8}})", text)
    return match.group(1) if match else "currentColor"


def unknown_variables(template: str) -> list[str]:
    found: list[str] = []
    for match in _VAR.finditer(template or ""):
        key = match.group(1).lower()
        if key not in _VARIABLES:
            found.append(key)
    return found


def fill_variables(template: str, values: dict[str, str]) -> str:
    """Substitute ``{name}``. Empty values disappear together with an adjacent separator."""

    def repl(match: re.Match[str]) -> str:
        raw_key = match.group(1).lower()
        key = _ALIAS.get(raw_key, raw_key)
        if key not in _VARIABLES:
            return match.group(0)
        raw = values.get(key, "")
        if raw is None or str(raw) == "":
            return _EMPTY
        if key in _RAW_HTML:
            return str(raw)
        return html.escape(str(raw))

    text = _VAR.sub(repl, template)
    text = re.sub(rf"(?:{_SEP}){_EMPTY}", "", text)
    text = re.sub(rf"{_EMPTY}(?:{_SEP})", "", text)
    text = re.sub(rf"[ \t]+{_EMPTY}", "", text)
    text = re.sub(rf"{_EMPTY}[ \t]+", "", text)
    return text.replace(_EMPTY, "")


def _initials(person: Person | None) -> str:
    if person is None:
        return ""
    first = (person.first_name[:1] if person.first_name else "").upper()
    last = (person.last_name[:1] if person.last_name else "").upper()
    return f"{first}{last}"


def _photo_html(person: Person | None) -> str:
    brand = _token("brand-primary-600")
    on_primary = _token("text-on-primary")
    if person is not None and person.photo_key:
        return f'<img src="cid:{PHOTO_CID}" alt="" width="72" height="80" style="display:block">'
    initials = html.escape(_initials(person) or "·")
    return (
        f'<div style="width:72px;height:80px;background:{brand};color:{on_primary};text-align:center;'
        f"line-height:80px;font-weight:700;font-size:16px;font-family:Arial,sans-serif;"
        f'clip-path:polygon(50% 0,100% 25%,100% 75%,50% 100%,0 75%,0 25%)">{initials}</div>'
    )


def _logo_html() -> str:
    return f'<img src="cid:{LOGO_CID}" alt="SMART" width="96" height="33" style="display:block">'


def _values(person: Person | None, branch: Branch | None, email: str) -> dict[str, str]:
    personal = (person.personal_email or "") if person else ""
    return {
        "meno": person.first_name if person else "",
        "priezvisko": person.last_name if person else "",
        "funkcia": (person.function or "") if person else "",
        "telefon": (person.phone or "") if person else "",
        "mobil": (person.mobile or "") if person else "",
        "email_osobny": personal,
        "email_pobocky": email,
        "email": email,
        "pobocka": branch.name if branch else "",
        "adresa_pobocky": (branch.address or "") if branch else "",
        "telefon_pobocky": (branch.phone or "") if branch else "",
        "oteviracie_hodiny": (branch.hours or "") if branch else "",
        "web": COMPANY_WEB,
        "firma": "Smart s.r.o.",
        "fotka": _photo_html(person),
        "logo": _logo_html(),
    }


_ASSETS = Path(__file__).resolve().parent / "assets" / "signature"
# Customer's card design (pilot, issue #36). Icons and logo are the customer's own PNGs. They are embedded as data:
# images; at send time outgoing_images turns every data: image into a CID part, so Gmail/Outlook show them.
_KARTA_TAGLINE = {
    "sk": "spojovací materiál",
    "cs": "spojovací materiál",
    "en": "fasteners",
    "de": "Verbindungselemente",
}
_KARTA_BUTTON = {
    "sk": "Nakupujte v e-shope smartsro.sk",
    "cs": "Nakupujte v e-shopu smartsro.sk",
    "en": "Shop online at smartsro.sk",
    "de": "Jetzt im Online-Shop smartsro.sk einkaufen",
}
_KARTA_ICON_ALT = {
    "sk": ("Tel.", "E-mail", "Adresa"),
    "cs": ("Tel.", "E-mail", "Adresa"),
    "en": ("Phone", "E-mail", "Address"),
    "de": ("Tel.", "E-Mail", "Adresse"),
}
_UTM = "utm_source=email&amp;utm_medium=podpis"


def _asset_data_uri(name: str) -> str:
    data = (_ASSETS / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def karta_template(lang: str = "sk") -> str:
    """Default branch template „Karta“ (SETTINGS 11c) in the customer's design: logo | name, function, icons, e-shop."""
    lang = lang if lang in _KARTA_BUTTON else "sk"
    brand = _token("brand-primary-600")
    text = _token("text-primary")
    muted = _token("text-secondary")
    on_brand = _token("text-on-primary")
    tagline = html.escape(_KARTA_TAGLINE[lang])
    button = html.escape(_KARTA_BUTTON[lang])
    alt_phone, alt_mail, alt_address = (html.escape(a) for a in _KARTA_ICON_ALT[lang])

    def icon(name: str, alt: str) -> str:
        return (
            '<td style="padding:2px 8px 2px 0;vertical-align:middle;">'
            f'<img src="{_asset_data_uri(name)}" width="20" height="20" alt="{alt}" style="display:block;border:0;">'
            "</td>"
        )

    cell = "padding:2px 0;vertical-align:middle;"
    link = f"color:{text};text-decoration:none;"
    return (
        '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;'
        f'font-family:Arial,Helvetica,sans-serif;color:{text};"><tr>'
        f'<td style="padding:0 16px 0 0;border-right:2px solid {brand};vertical-align:middle;">'
        f'<a href="{COMPANY_WEB_URL}?{_UTM}&amp;utm_campaign=logo" style="text-decoration:none;">'
        f'<img src="{_asset_data_uri("logo")}" width="150" height="51" alt="SMART s.r.o." '
        'style="display:block;border:0;"></a>'
        f'<div style="font-size:11px;color:{muted};padding-top:6px;letter-spacing:0.3px;">{tagline}</div>'
        "</td>"
        '<td style="padding:0 0 0 16px;vertical-align:middle;">'
        f'<div style="font-size:16px;font-weight:bold;color:{brand};line-height:20px;">{{meno}} {{priezvisko}}</div>'
        f'<div style="font-size:12px;color:{muted};line-height:18px;padding-bottom:8px;">'
        "{funkcia} · {pobocka}</div>"
        '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;font-size:12px;'
        'line-height:20px;">'
        f'<tr>{icon("phone", alt_phone)}<td style="{cell}">'
        f'<a href="tel:{{mobil}}" style="{link}">{{mobil}}</a></td></tr>'
        f'<tr>{icon("email", alt_mail)}<td style="{cell}">'
        f'<a href="mailto:{{email_pobocky}}" style="{link}">{{email_pobocky}}</a></td></tr>'
        f'<tr>{icon("address", alt_address)}<td style="{cell}color:{text};">{{adresa_pobocky}}</td></tr>'
        "</table>"
        '<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-top:10px;"><tr>'
        f'<td style="background:{brand};border-radius:6px;padding:7px 14px;">'
        f'<a href="{COMPANY_WEB_URL}?{_UTM}&amp;utm_campaign=eshop" style="color:{on_brand};text-decoration:none;'
        'font-size:12px;font-weight:bold;white-space:nowrap;">'
        f'<img src="{_asset_data_uri("cart")}" width="16" height="16" alt="" style="border:0;vertical-align:-3px;">'
        f"&nbsp; {button} &rarr;</a>"
        "</td></tr></table>"
        "</td></tr></table>"
    )


def text_template(lang: str = "sk") -> str:
    """Second preset „Text“ (SETTINGS 11c)."""
    greet = html.escape(_GREET_TEXT.get(lang, _GREET_TEXT["sk"]))
    return (
        f"<p>{greet}</p>"
        "<p><strong>{meno} {priezvisko}</strong><br>{funkcia} · {mobil}<br>"
        "Smart s.r.o. – {pobocka}<br>{adresa_pobocky} · {telefon_pobocky}</p>"
    )


def signature_presets() -> dict[str, dict[str, str]]:
    return {
        "karta": {lang: karta_template(lang) for lang in SIGNATURE_LANGS},
        "text": {lang: text_template(lang) for lang in SIGNATURE_LANGS},
    }


def default_branch_template() -> dict[str, str]:
    """Fictional starter used when a branch is created. Slovak „Karta“, plus the other languages."""
    return {lang: karta_template(lang) for lang in SIGNATURE_LANGS}


def apply_signature_languages(raw: dict[str, str], *, require_sk: bool) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Sanitise each language. Branch templates must keep a non-empty SK body and known variables only."""
    cleaned: dict[str, str] = {}
    stripped: dict[str, list[str]] = {}
    unknown: list[str] = []
    for lang, body in raw.items():
        key = (lang or "").lower()[:2]
        if key == "cz":
            key = "cs"
        if key not in SIGNATURE_LANGS:
            continue
        html_body = body or ""
        if require_sk:
            unknown.extend(unknown_variables(html_body))
        text, gone = sanitize_signature_html(html_body)
        if len(text.encode("utf-8")) > SIGNATURE_MAX_BYTES:
            raise SignatureError("signature_too_large")
        cleaned[key] = text
        if gone:
            stripped[key] = gone
    if require_sk and not cleaned.get("sk", "").strip():
        raise SignatureError("signature_sk_required")
    if not require_sk and any(value.strip() for value in cleaned.values()) and not cleaned.get("sk", "").strip():
        raise SignatureError("signature_sk_required")
    if unknown:
        raise SignatureError("unknown_signature_variable", names=sorted(set(unknown)))
    return cleaned, stripped


def render_signature(
    *,
    person: Person | None,
    branch: Branch | None,
    identity: Identity | None,
    email: str,
    language: str = "sk",
    override_html: str | None = None,
) -> str:
    """HTML signature block for the draft (sanitised, ≤ 64 kB). https image URLs stay (D22)."""
    if override_html is not None:
        text, _gone = sanitize_signature_html(override_html[: SIGNATURE_MAX_BYTES + 1])
        return text
    values = _values(person, branch, email)
    lang = language.lower()[:2] or "sk"
    if lang == "cz":
        lang = "cs"
    template = ""
    if branch and isinstance(branch.signature_template_html, dict):
        template = branch.signature_template_html.get(lang) or branch.signature_template_html.get("sk") or ""
    if not template and identity and isinstance(identity.signature_html, dict):
        template = identity.signature_html.get(lang) or identity.signature_html.get("sk") or ""
    if not template and person:
        parts = [
            f"<p><strong>{html.escape(person.full_name)}</strong>",
            f"<br>{html.escape(person.function)}" if person.function else "",
            f"<br>{html.escape(branch.name)}" if branch else "",
            f"<br>{html.escape(email)}</p>",
        ]
        template = "".join(parts)
    filled = fill_variables(template, values)
    text, _gone = sanitize_signature_html(filled[: SIGNATURE_MAX_BYTES + 1])
    return text


def preview_signature_html(
    *,
    person: Person | None,
    branch: Branch | None,
    identity: Identity | None,
    email: str,
    language: str = "sk",
) -> str:
    """Same as render, but the logo CID points at the app logo so the settings preview can show it."""
    rendered = render_signature(person=person, branch=branch, identity=identity, email=email, language=language)
    return rendered.replace(f"cid:{LOGO_CID}", "/logo-smart.svg")


def html_to_text(html_body: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", html_body)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</tr>", "\n", text)
    text = re.sub(r"(?i)</div>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()
