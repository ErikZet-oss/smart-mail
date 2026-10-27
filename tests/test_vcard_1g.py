"""vCard parse/serialize — Roundcube export, diacritics, multi email/phone, bad file."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.contacts.vcard import VCardError, parse_vcards, serialize_vcards

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "contacts"


def test_1g_parse_roundcube_export_diacritics_and_multi() -> None:
    text = (FIXTURES / "roundcube_export.vcf").read_text(encoding="utf-8")
    contacts = parse_vcards(text)
    assert len(contacts) == 3
    jan = next(c for c in contacts if "Novák" in c.display_name)
    assert jan.first_name == "Ján"
    assert jan.last_name == "Novák"
    assert len(jan.emails) == 2
    assert {e["email"] for e in jan.emails} == {"jan.novak@smartmail.test", "jan.home@smartmail.test"}
    assert len(jan.phones) == 2
    assert all(e["email"].endswith("@smartmail.test") for c in contacts for e in c.emails)
    maria = next(c for c in contacts if "Čéna" in (c.display_name or ""))
    assert maria.emails[0]["email"] == "maria.cena@smartmail.test"


def test_1g_serialize_round_trip() -> None:
    text = (FIXTURES / "roundcube_export.vcf").read_text(encoding="utf-8")
    again = parse_vcards(serialize_vcards(parse_vcards(text)))
    assert len(again) == 3
    assert any("Trenčín" in (c.display_name or "") for c in again)


def test_1g_bad_vcard_raises() -> None:
    bad = (FIXTURES / "bad_file.vcf").read_text(encoding="utf-8")
    with pytest.raises(VCardError):
        parse_vcards(bad)


def test_1g_empty_vcard_raises() -> None:
    with pytest.raises(VCardError):
        parse_vcards("   ")
