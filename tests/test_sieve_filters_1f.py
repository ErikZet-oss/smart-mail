"""Phase 1f ManageSieve: Roundcube round-trip, Od→folder, vacation in same script."""

from __future__ import annotations

from pathlib import Path

from app.mail.sieve import (
    FilterAction,
    FilterCondition,
    FilterRule,
    VacationSettings,
    apply_vacation_to_script,
    compile_filters,
    compile_script,
    parse_roundcube_script,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sieve" / "roundcube_filters.sieve"


def test_1f_roundcube_fixture_loads_od_and_readonly() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_roundcube_script(raw)
    assert len(parsed.rules) == 4
    acme = next(r for r in parsed.rules if r.name == "Dodávatelia Acme")
    assert acme.editable is True
    assert acme.enabled is True
    assert [(c.field, c.op, c.value) for c in acme.conditions] == [
        ("from", "contains", "objednavky@acme-parts.test"),
        ("from", "contains", "@acme-parts.test"),
    ]
    assert acme.actions[0].type == "fileinto" and acme.actions[0].value == "Dodávatelia"
    disabled = next(r for r in parsed.rules if "Faktúry" in r.name)
    assert disabled.enabled is False
    assert disabled.conditions[0].field == "subject"
    regex = next(r for r in parsed.rules if "Regex" in r.name)
    assert regex.editable is False
    assert ":regex" in (regex.raw or "")


def test_1f_unchanged_round_trip_is_identical() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_roundcube_script(raw)
    out = compile_script(parsed, include_vacation=False)
    assert out == raw


def test_1f_od_filter_keeps_condition_after_compile() -> None:
    script = compile_filters(
        [
            FilterRule(
                id="f1",
                name="Od Acme",
                conditions=[FilterCondition("from", "contains", "@acme-parts.test")],
                actions=[FilterAction("fileinto", "Dodávatelia"), FilterAction("stop")],
            )
        ]
    )
    assert 'address :contains "From" "@acme-parts.test"' in script
    assert 'fileinto "Dodávatelia"' in script
    parsed = parse_roundcube_script(script)
    assert len(parsed.rules) == 1
    assert parsed.rules[0].conditions[0].field == "from"
    assert parsed.rules[0].conditions[0].value == "@acme-parts.test"
    # load → save with raw preserved stays identical
    again = compile_script(parsed, include_vacation=False)
    assert again == script


def test_1f_vacation_on_off_does_not_change_filters_or_active_set_name() -> None:
    raw = FIXTURE.read_text(encoding="utf-8")
    vac_on = VacationSettings(
        enabled=True,
        subject="Mimo kancelárie: {predmet}",
        body_sk="Som mimo kancelárie (test).",
        body_en="Out of office (test).",
        body_de="Außer Haus (Test).",
        days=3,
        start="2026-10-27T00:00:00",
        end="2026-11-03T23:59:59",
    )
    with_vac = apply_vacation_to_script(raw, vac_on, script_name="roundcube")
    assert 'fileinto "Dodávatelia"' in with_vac
    assert "smartmail:vacation" in with_vac
    assert "vacation :days 3" in with_vac
    assert 'currentdate :value "ge"' in with_vac

    off = apply_vacation_to_script(with_vac, VacationSettings(enabled=False), script_name="roundcube")
    p_raw = parse_roundcube_script(raw)
    p_off = parse_roundcube_script(off)
    assert [r.raw for r in p_raw.rules] == [r.raw for r in p_off.rules if r.kind != "vacation"]
    # disabled vacation may remain as a commented rule; filter names unchanged
    names = [r.name for r in p_off.rules if r.kind != "vacation"]
    assert names == [r.name for r in p_raw.rules]


def test_1f_filters_to_dicts_readonly_label() -> None:
    from app.mail.sieve import filters_to_dicts

    raw = FIXTURE.read_text(encoding="utf-8")
    parsed = parse_roundcube_script(raw)
    dicts = filters_to_dicts(parsed.rules)
    regex = next(d for d in dicts if "Regex" in d["name"])
    assert regex["editable"] is False
    assert regex["readonly_label"] == "Pravidlo z Roundcube (len na čítanie)"
    acme = next(d for d in dicts if d["name"] == "Dodávatelia Acme")
    assert acme["conditions"][0]["field"] == "from"
    assert acme["raw"]
