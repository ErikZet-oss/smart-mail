"""Pilot 2026-10-31: the classifier LLM answered „pl“ for a Slovak e-mail and the reply suggestion was in Polish.
A clear heuristic result must win over the LLM; the LLM decides only when the heuristic is unsure."""

from __future__ import annotations

from app.ai.language import final_language, is_confident

SLOVAK = (
    "Faktúra\nDobrý deň, potreboval by som poslať našu poslednú faktúru.\n\nPROXTON Engineering s.r.o.\n"
    "Rokošova I 237/62\n951 31 Močenok\nSlovakia\nIČO: 51818353\nIČ DPH: SK2120802948"
)


def test_clear_slovak_beats_llm_polish() -> None:
    assert is_confident(SLOVAK)
    assert final_language(SLOVAK, "pl") == "sk"


def test_llm_decides_when_heuristic_found_nothing() -> None:
    assert final_language("OK, 15:00", "en") == "en"
    assert final_language("OK, 15:00", None) == "other"


def test_llm_decides_when_heuristic_is_unsure() -> None:
    text = "Hello Ľubo, see attached."  # one Slovak letter in a name, no English keyword
    assert not is_confident(text)
    assert final_language(text, "en") == "en"


def test_same_answer_is_kept() -> None:
    assert final_language("Please send the invoice, thanks. Order 42, delivery today.", "en") == "en"
