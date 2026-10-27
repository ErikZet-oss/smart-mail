"""Phase 2b: deterministic rules, language, classify schema, phishing notes."""

from __future__ import annotations

import pytest

from app.ai.classify import ClassificationResult, parse_classification_json, phishing_signals
from app.ai.language import detect_language
from app.ai.rules import apply_rules


def test_2b_rule_list_unsubscribe_is_newsletter() -> None:
    hit = apply_rules(
        from_email="news@vendor.test",
        subject="Tips",
        headers_text="List-Unsubscribe: <https://x.test/u>",
        attachment_names=[],
        auth_results=None,
        internal_domains=["smartsro.sk"],
    )
    assert hit is not None
    assert hit.category == "newsletter"
    assert hit.decisive is True


def test_2b_rule_internal_domain() -> None:
    hit = apply_rules(
        from_email="jana@smartsro.sk",
        subject="Porada",
        headers_text="",
        attachment_names=[],
        auth_results=None,
        internal_domains=["smartsro.sk"],
    )
    assert hit is not None and hit.category == "internal" and hit.decisive


def test_2b_rule_isdoc_supplier_document() -> None:
    hit = apply_rules(
        from_email="dodavatel@example.test",
        subject="Faktura",
        headers_text="",
        attachment_names=["doklad.isdoc"],
        auth_results=None,
        internal_domains=["smartsro.sk"],
    )
    assert hit is not None and hit.category == "supplier_document" and hit.decisive


def test_2b_rule_dmarc_fail_spam_candidate_not_decisive() -> None:
    hit = apply_rules(
        from_email="evil@phish.test",
        subject="Urgent",
        headers_text="",
        attachment_names=[],
        auth_results={"dmarc": "fail", "spf": "fail"},
        internal_domains=["smartsro.sk"],
    )
    assert hit is not None
    assert hit.category == "spam"
    assert hit.decisive is False
    assert "security_dmarc_fail" in hit.notes


def test_2b_language_sk_vs_en() -> None:
    assert detect_language("Dobrý deň, prosím o cenovú ponuku na skrutky M8.") == "sk"
    assert detect_language("Please send a quote for DIN 933 screws.") == "en"


def test_2b_classify_schema_rejects_unknown_category() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClassificationResult(category="not_a_real_category")


def test_2b_parse_classification_json() -> None:
    raw = (
        '{"category":"inquiry","priority":"normal","language":"sk",'
        '"needs_reply":true,"summary_sk":"Dopyt M8","entities":{},"confidence":0.9}'
    )
    parsed = parse_classification_json(raw)
    assert parsed.category == "inquiry"
    assert parsed.summary_sk == "Dopyt M8"


def test_2b_phishing_display_spoof_and_iban() -> None:
    notes = phishing_signals(
        from_name="Smart s.r.o. účtovňa",
        from_email="attacker@evil.test",
        auth_results={"dmarc": "fail"},
        body_text="Prosím o zmenu IBAN SK3112000000198742637541 na nový účet.",
        internal_domains=["smartsro.sk"],
    )
    assert "security_dmarc_fail" in notes
    assert "security_display_spoof" in notes
    assert "security_iban_change" in notes


@pytest.mark.asyncio
async def test_2b_classify_decisive_rule_skips_llm() -> None:
    from app.ai.classify import classify_message
    from app.ai.provider import get_llm_provider
    from app.core.config import Settings

    settings = Settings(
        app_env="test",
        app_base_url="http://test",
        app_secret_key="test-secret-key-that-is-long-enough-0123456789",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        redis_url="redis://localhost:6379/0",
        llm_provider="anthropic",
        anthropic_api_key=None,
        llm_model_classify="claude-haiku-4-5-20251001",
    )
    outcome = await classify_message(
        provider=get_llm_provider(settings),
        model="claude-test",
        from_email="news@vendor.test",
        from_name="Vendor",
        subject="Tips",
        body_text="Hello",
        headers_text="List-Unsubscribe: <https://x.test/u>",
        attachment_names=[],
        auth_results=None,
        internal_domains=["smartsro.sk"],
    )
    assert outcome.source == "rules"
    assert outcome.result.category == "newsletter"
    assert outcome.ai_run_cost_usd == 0


def test_2b_private_folder_skipped() -> None:
    from types import SimpleNamespace

    from app.ai.pipeline import folder_eligible_for_ai

    private = SimpleNamespace(subscribed=True, selectable=True, private=True, special_use=None)
    assert folder_eligible_for_ai(private) is False  # type: ignore[arg-type]


def test_2b_triage_categories_match_figma_order() -> None:
    from app.ai.categories import TRIAGE_CATEGORIES

    assert [c.id for c in TRIAGE_CATEGORIES] == [
        "inquiry",
        "order",
        "invoice_request",
        "supplier_document",
        "complaint",
        "shipping",
        "payment",
        "document_request",
        "supplier_info",
        "newsletter",
    ]
