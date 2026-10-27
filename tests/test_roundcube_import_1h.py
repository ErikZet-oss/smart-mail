"""tools/roundcube_import.py — vCard + identities + Odpovede (no filters); fictional fixtures only."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.roundcube_import import (
    _email_ok_for_fixture,
    load_identities_json,
    load_responses_json,
    load_vcard_summary,
    main,
)

ROOT = Path(__file__).resolve().parents[1]
VCARD = ROOT / "fixtures/contacts/roundcube_export.vcf"
IDENTITIES = ROOT / "fixtures/roundcube/identities.json"
RESPONSES = ROOT / "fixtures/roundcube/responses.json"


def test_1h_fixture_emails_are_fictional() -> None:
    assert _email_ok_for_fixture("pilot@smartmail.test")
    assert not _email_ok_for_fixture("jan@real-customer.sk")


def test_1h_load_vcard_and_json_fixtures() -> None:
    names = load_vcard_summary(VCARD)
    assert any("Ján Novák" in n for n in names)
    assert all("@smartmail.test" in n or n.endswith(">") for n in names)

    identities = load_identities_json(IDENTITIES)
    assert len(identities) >= 1
    assert identities[0].email.endswith("@smartmail.test")
    assert identities[0].signature_html.get("sk")

    responses = load_responses_json(RESPONSES)
    assert any(r.name == "Poďakovanie" for r in responses)
    assert any(r.shared for r in responses)


def test_1h_cli_dry_run_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--account",
            "pilot@smartmail.test",
            "--vcard",
            str(VCARD),
            "--identities",
            str(IDENTITIES),
            "--responses",
            str(RESPONSES),
            "--dry-run",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "Filters: skipped" in out
    assert "Dry-run only" in out
    assert "Poďakovanie" in out
