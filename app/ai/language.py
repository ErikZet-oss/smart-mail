"""Cheap language detection for classify (AI_ASSISTANT §2 step 2)."""

from __future__ import annotations

import re

# Characteristic words / digraphs — good enough for triage; LLM may refine.
_SK = re.compile(
    r"\b(ďakujem|prosím|objednávk|dopyt|faktúr|dodací|tovar|skrutk|podložk|matic)\w*\b|"
    r"[ľšťžýáíéúôňď]",
    re.I,
)
_CS = re.compile(
    r"\b(děkuji|prosím|objednávk|poptávk|faktúr|dodací|zboží|šroub)\w*\b|" r"[řěů]",
    re.I,
)
_DE = re.compile(
    r"\b(bitte|danke|bestellung|rechnung|lieferung|schraube|anfrage|angebot)\w*\b|" r"[äöüß]",
    re.I,
)
_EN = re.compile(
    r"\b(please|thanks|order|invoice|delivery|quote|inquiry|screw|nut|washer)\w*\b",
    re.I,
)
_PL = re.compile(
    r"\b(proszę|dziękuję|zamówien|faktur|dostaw|śrub)\w*\b|" r"[ąćęłńóśźż]",
    re.I,
)
_HU = re.compile(
    r"\b(köszönöm|kérem|rendelés|számla|szállítás)\w*\b|" r"[őűöüáéíóú]",
    re.I,
)


def detect_language(text: str) -> str:
    """Return sk|cs|en|de|pl|hu|other from plain text (subject + body)."""
    sample = (text or "")[:4000]
    if not sample.strip():
        return "other"
    scores: list[tuple[int, str]] = [
        (len(_SK.findall(sample)), "sk"),
        (len(_CS.findall(sample)), "cs"),
        (len(_DE.findall(sample)), "de"),
        (len(_EN.findall(sample)), "en"),
        (len(_PL.findall(sample)), "pl"),
        (len(_HU.findall(sample)), "hu"),
    ]
    scores.sort(key=lambda x: x[0], reverse=True)
    best_n, best = scores[0]
    if best_n == 0:
        return "other"
    # Slovak vs Czech: prefer sk when tied-ish with Slovak-specific chars
    if best == "cs" and scores[1][1] == "sk" and scores[1][0] >= best_n - 1:
        return "sk"
    return best
