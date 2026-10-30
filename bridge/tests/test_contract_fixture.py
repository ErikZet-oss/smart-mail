import json

from tests.contract_fixture import FIXTURE, current


def test_mock_output_matches_the_contract_fixture() -> None:
    """If this fails, the bridge models changed: regenerate the fixture and update app/money/schemas.py."""
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == current()
