"""vCard parse/serialize — Roundcube export, diacritics, multi email/phone, bad file."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.contacts.vcard import VCardError, VCardTooLarge, parse_vcards, serialize_vcards

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


def test_1g_vcard21_quoted_printable_slovak() -> None:
    text = (FIXTURES / "vcard21_slovak_qp.vcf").read_text(encoding="utf-8")
    contacts = parse_vcards(text)
    assert len(contacts) == 1
    c = contacts[0]
    assert c.display_name == "Ján Novák"
    assert c.first_name == "Ján"
    assert c.last_name == "Novák"
    assert c.organization == "Pobočka Trenčín"
    assert c.emails[0]["email"] == "jan.qp@smartmail.test"
    assert c.notes is not None and "čéna" in c.notes


def test_1g_vcard21_windows1250_quoted_printable_slovak() -> None:
    text = (FIXTURES / "vcard21_slovak_cp1250.vcf").read_text(encoding="utf-8")
    contacts = parse_vcards(text)
    assert len(contacts) == 1
    c = contacts[0]
    assert c.display_name == "Mária Čéna"
    assert c.first_name == "Mária"
    assert c.last_name == "Čéna"
    assert c.organization == "Pobočka Trenčín"
    assert c.emails[0]["email"] == "maria.cp1250@smartmail.test"
    assert c.notes is not None and "faktúra" in c.notes and "cena" in c.notes


def test_1g_vcard_too_many_contacts() -> None:
    card = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:X\r\nEMAIL:a@smartmail.test\r\nEND:VCARD\r\n"
    with pytest.raises(VCardTooLarge):
        parse_vcards(card * 3, max_contacts=2)
