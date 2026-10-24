"""Backend check on a suggested safer wording for an UNVERIFIED claim ("the backend never trusts
the engine"). Product rules: docs/backend.md, "Safer wording for unverified claims".

An unverified claim has no evidence, so - unlike a contradicted claim's correction - a softened
wording can't be checked against a quote. What CAN be checked deterministically is enforced here,
on the whole claim span before and after the edit:

* never invent facts: the rewrite adds no number that wasn't already in the claim;
* no unproven ranking or superlative survives or appears ("number one", "#1", "best",
  "leading", "fastest", "only", ... - see RANKING_TERMS): replacing one with another is refused;
* product names, prices and dates are unchanged: every number, currency symbol, month name and
  capitalised name in the original claim is still in the rewrite;
* it is a real, single-line change (not empty, not identical, no hidden/control characters).

A suggestion that fails any check is dropped (the finding keeps `suggested_correction = null`).
Passing does not make the claim verified: the finding stays `unverified`, and the suggestion is
only offered - the user decides; nothing is applied automatically.
"""

from __future__ import annotations

import re

from inkloom_verify.schemas import numbers_in
from inkloom_verify.security import has_hidden_characters

# Unproven rankings / superlatives. Multi-word and symbol forms first; single words are matched
# as whole words. Kept deliberately broad: a false refusal only means no suggestion is shown.
RANKING_TERMS = (
    "number one", "number 1", "no. 1", "no.1", "#1", "best", "leading", "fastest", "only", "top",
    "largest", "biggest", "cheapest", "most", "first", "greatest", "strongest", "ultimate",
    "unbeatable", "unmatched", "unrivalled", "unrivaled", "world-class", "best-selling",
    "industry-leading", "market-leading", "no 1",
)
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
)
_CURRENCY = re.compile(r"[€$£¥₹%]")
_CAPITALISED = re.compile(r"\b([A-Z][\w-]*)")


def _has_term(term: str, text: str) -> bool:
    if term[0].isalnum() and term[-1].isalnum():
        return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text) is not None
    return term in text


def ranking_terms_in(text: str) -> list[str]:
    folded = text.casefold()
    return [term for term in RANKING_TERMS if _has_term(term, folded)]


def _names(text: str) -> set[str]:
    """Capitalised words, possessive dropped, ignoring the span's first word (sentence case)
    and any ranking term (those are meant to go)."""
    words = [m.group(1) for m in _CAPITALISED.finditer(text)]
    first = text.split(maxsplit=1)[0] if text.split() else ""
    names = set()
    for word in words:
        stem = re.sub(r"['’]s$", "", word)
        if word == first or stem.casefold() in RANKING_TERMS or stem.casefold() in _MONTHS:
            continue
        names.add(stem)
    return names


def softening_issues(original: str, rewritten: str) -> list[str]:
    """Empty when `rewritten` (the whole claim span after the edit) may be offered."""
    if not rewritten.strip() or " ".join(rewritten.split()) == " ".join(original.split()):
        return ["no_change"]
    issues = []
    if has_hidden_characters(rewritten):
        issues.append("hidden_characters")
    added_numbers = numbers_in(rewritten) - numbers_in(original)
    if added_numbers:
        issues.append("adds_numbers:" + ",".join(sorted(added_numbers)))
    rankings = ranking_terms_in(rewritten)
    if rankings:
        issues.append("unproven_ranking:" + ",".join(rankings))
    if not numbers_in(original) <= numbers_in(rewritten):
        issues.append("drops_number")
    if not set(_CURRENCY.findall(original)) <= set(_CURRENCY.findall(rewritten)):
        issues.append("drops_currency")
    months_before = {m for m in _MONTHS if _has_term(m, original.casefold())}
    if not months_before <= {m for m in _MONTHS if _has_term(m, rewritten.casefold())}:
        issues.append("drops_date")
    missing = sorted(name for name in _names(original) if name not in rewritten)
    if missing:
        issues.append("drops_name:" + ",".join(missing))
    return issues
