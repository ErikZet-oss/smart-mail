"""Vacation: one Sieve rule, combined SK/EN/DE body, subject via variables (Phase 1h-e follow-up)."""

from __future__ import annotations

from pathlib import Path

from app.mail.sieve import (
    VACATION_BODY_SEPARATOR,
    VACATION_MARKER,
    VACATION_MARKER_DE,
    VACATION_MARKER_EN,
    VACATION_RULE_NAME,
    VacationSettings,
    apply_vacation_to_script,
    compile_vacation_rule,
    parse_roundcube_script,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/sieve/roundcube_filters.sieve"

# Legacy three-rule script (Accept-Language + stop) from the previous 1h-e shape — load must merge.
LEGACY_THREE_RULE = """\
require ["fileinto","reject","vacation","date","relational","imap4flags"];
# rule:[Dodávatelia Acme]
if address :contains "From" "acme@example.test"
{
	fileinto "Dodávatelia";
	stop;
}
# rule:[Mimo kancelárie EN]
# smartmail:vacation:en
if header :comparator "i;ascii-casemap" :matches "Accept-Language" "*en*" {
	vacation :days 5 :subject "Mimo kancelárie: %s"
	"I am out of office (EN).";
	stop;
}
# rule:[Mimo kancelárie DE]
# smartmail:vacation:de
if header :comparator "i;ascii-casemap" :matches "Accept-Language" "*de*" {
	vacation :days 5 :subject "Mimo kancelárie: %s"
	"Ich bin außer Haus (DE).";
	stop;
}
# rule:[Mimo kancelárie]
# smartmail:vacation
if true {
	vacation :days 5 :subject "Mimo kancelárie: %s"
	"Som mimo kancelárie (SK).";
}
"""


def test_1h_vacation_single_rule_combined_sk_en_de_body() -> None:
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
    script = apply_vacation_to_script(raw, vac, script_name="roundcube", supports_variables=True)
    assert 'fileinto "Dodávatelia"' in script  # filters untouched
    assert VACATION_MARKER in script
    assert VACATION_MARKER_EN not in script
    assert VACATION_MARKER_DE not in script
    assert "Accept-Language" not in script
    assert "\tstop;" not in script.split(VACATION_MARKER, 1)[-1]
    assert script.count(f"# rule:[{VACATION_RULE_NAME}]") == 1
    assert script.count("vacation :days") == 1
    combined = VACATION_BODY_SEPARATOR.join(
        [
            "Som mimo kancelárie (SK).",
            "I am out of office (EN).",
            "Ich bin außer Haus (DE).",
        ]
    )
    assert combined in script
    assert "require [" in script and '"variables"' in script

    parsed = parse_roundcube_script(script, script_name="roundcube")
    vac_rules = [r for r in parsed.rules if r.kind == "vacation"]
    assert len(vac_rules) == 1
    assert parsed.vacation.enabled is True
    assert parsed.vacation.body_sk.startswith("Som mimo kancelárie")
    assert parsed.vacation.body_en.startswith("I am out of office")
    assert parsed.vacation.body_de.startswith("Ich bin außer Haus")


def test_1h_vacation_subject_uses_variables_orig() -> None:
    rule = compile_vacation_rule(
        VacationSettings(
            enabled=True,
            subject="Mimo kancelárie: {predmet}",
            body_sk="SK text",
            body_en="",
            body_de="",
            days=7,
        ),
        supports_variables=True,
    )
    assert 'if header :matches "subject" "*"' in rule
    assert 'set "orig" "${1}"' in rule
    assert ':subject "Mimo kancelárie: ${orig}"' in rule
    assert "%s" not in rule  # Sieve does not expand %s


def test_1h_vacation_omits_subject_without_variables() -> None:
    rule = compile_vacation_rule(
        VacationSettings(enabled=True, subject="Mimo kancelárie: {predmet}", body_sk="SK"),
        supports_variables=False,
    )
    assert ":subject" not in rule
    assert 'set "orig"' not in rule
    assert "variables" not in rule


def test_1h_vacation_skips_empty_en_de_parts() -> None:
    rule = compile_vacation_rule(
        VacationSettings(enabled=True, body_sk="Iba SK.", body_en="  ", body_de=""),
        supports_variables=True,
    )
    assert "Iba SK." in rule
    assert VACATION_BODY_SEPARATOR not in rule


def test_1h_vacation_load_merges_legacy_three_rules() -> None:
    parsed = parse_roundcube_script(LEGACY_THREE_RULE, script_name="roundcube")
    assert parsed.vacation.enabled is True
    assert parsed.vacation.body_sk.startswith("Som mimo kancelárie")
    assert parsed.vacation.body_en.startswith("I am out of office")
    assert parsed.vacation.body_de.startswith("Ich bin außer Haus")
    # Re-save → one rule, no Accept-Language
    out = apply_vacation_to_script(LEGACY_THREE_RULE, parsed.vacation, script_name="roundcube", supports_variables=True)
    assert VACATION_MARKER_EN not in out
    assert VACATION_MARKER_DE not in out
    assert "Accept-Language" not in out
    assert out.count("vacation :days") == 1
    assert (
        VACATION_BODY_SEPARATOR.join(
            [
                parsed.vacation.body_sk.strip(),
                parsed.vacation.body_en.strip(),
                parsed.vacation.body_de.strip(),
            ]
        )
        in out
    )


def test_1h_vacation_off_removes_en_de_and_keeps_filters() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    on = apply_vacation_to_script(
        raw,
        VacationSettings(enabled=True, body_sk="SK", body_en="EN", body_de="DE"),
        script_name="roundcube",
        supports_variables=True,
    )
    assert VACATION_MARKER in on and VACATION_MARKER_EN not in on
    off = apply_vacation_to_script(
        on, VacationSettings(enabled=False), script_name="roundcube", supports_variables=True
    )
    assert VACATION_MARKER_EN not in off
    assert VACATION_MARKER_DE not in off
    p_raw = parse_roundcube_script(raw)
    p_off = parse_roundcube_script(off)
    assert [r.name for r in p_off.rules if r.kind != "vacation"] == [r.name for r in p_raw.rules]
