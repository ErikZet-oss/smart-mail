"""Vacation EN/DE as extra rules in the same active ManageSieve script (Phase 1h-e debt)."""

from __future__ import annotations

from pathlib import Path

from app.mail.sieve import (
    VACATION_MARKER,
    VACATION_MARKER_DE,
    VACATION_MARKER_EN,
    VacationSettings,
    apply_vacation_to_script,
    parse_roundcube_script,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/sieve/roundcube_filters.sieve"


def test_1h_vacation_writes_en_de_rules_with_accept_language() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    vac = VacationSettings(
        enabled=True,
        subject="Mimo kancelárie: {predmet}",
        body_sk="Som mimo kancelárie (SK).",
        body_en="I am out of office (EN).",
        body_de="Ich bin außer Haus (DE).",
        days=5,
        start="2026-10-27T00:00:00",
        end="2026-11-03T23:59:59",
    )
    script = apply_vacation_to_script(raw, vac, script_name="roundcube")
    assert 'fileinto "Dodávatelia"' in script  # filters untouched
    assert VACATION_MARKER_EN in script
    assert VACATION_MARKER_DE in script
    assert VACATION_MARKER in script
    assert 'Accept-Language" "*en*"' in script or 'Accept-Language" "*en*"' in script.replace(" ", "")
    assert "*en*" in script and "*de*" in script
    assert "I am out of office (EN)." in script
    assert "Ich bin außer Haus (DE)." in script
    assert "Som mimo kancelárie (SK)." in script
    assert script.count("\tstop;") >= 2  # EN + DE stop before SK fallback

    parsed = parse_roundcube_script(script, script_name="roundcube")
    vac_rules = [r for r in parsed.rules if r.kind == "vacation"]
    assert len(vac_rules) == 3
    assert parsed.vacation.enabled is True
    assert parsed.vacation.body_en.startswith("I am out of office")
    assert parsed.vacation.body_de.startswith("Ich bin außer Haus")
    assert parsed.vacation.body_sk.startswith("Som mimo kancelárie")


def test_1h_vacation_off_removes_en_de_and_keeps_filters() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    on = apply_vacation_to_script(
        raw,
        VacationSettings(enabled=True, body_sk="SK", body_en="EN", body_de="DE"),
        script_name="roundcube",
    )
    assert VACATION_MARKER_EN in on and VACATION_MARKER in on
    off = apply_vacation_to_script(on, VacationSettings(enabled=False), script_name="roundcube")
    assert VACATION_MARKER_EN not in off
    assert VACATION_MARKER_DE not in off
    p_raw = parse_roundcube_script(raw)
    p_off = parse_roundcube_script(off)
    assert [r.name for r in p_off.rules if r.kind != "vacation"] == [r.name for r in p_raw.rules]
