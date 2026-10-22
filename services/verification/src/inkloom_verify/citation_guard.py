"""The citation guard: deterministic checks on every quotation a model offers as evidence.

A quotation is accepted only if:

1. it names a passage that was retrieved for this claim;
2. that passage is exactly the text of a reference document in this request (same doc_id, same
   text hash, same span);
3. the quotation occurs in that passage after normalisation (defined below);
4. it has at least two words;
5. it does not start after a negation in the same clause ("not dishwasher safe" quoted as
   "dishwasher safe").

Normalisation is applied to both the quotation and the passage, and nothing else is changed:

* curly and other typographic quotation marks become ``'`` or ``"``;
* every run of whitespace (spaces, tabs, newlines, non-breaking spaces) becomes one space;
* leading and trailing whitespace is removed.

Case, Unicode forms, hyphens, dashes and all other punctuation must match exactly. The accepted
quotation is stored as the passage's original text at the matched location, so it satisfies the
exact-match rules of the Citation contract.

Passing the guard means the words are really in the evidence. It does not mean they support the
verdict; that is measured by the evaluation harness, not assumed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from inkloom_verify.chunking import sentence_spans
from inkloom_verify.extraction import MONTHS, NEGATION
from inkloom_verify.schemas import (
    MAX_PASSAGE_CHARS,
    Citation,
    EvidencePassage,
    GuardRejectionReason,
    ReferenceDocument,
    SourceSpan,
)

_QUOTE_MARKS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
}
_CLAUSE_BREAK = re.compile(r"[,;:()–—]")
_WORD = re.compile(r"\w+")
MIN_QUOTE_WORDS = 2


def normalize(text: str) -> tuple[str, list[int]]:
    """The normalised text, and for each of its characters the index it came from in ``text``."""
    out: list[str] = []
    origin: list[int] = []
    pending_space = -1
    for index, char in enumerate(text):
        if char.isspace():
            if out and pending_space < 0:
                pending_space = index
            continue
        if pending_space >= 0:
            out.append(" ")
            origin.append(pending_space)
            pending_space = -1
        out.append(_QUOTE_MARKS.get(char, char))
        origin.append(index)
    return "".join(out), origin


def find_quote(quote: str, passage_text: str) -> tuple[int, int] | None:
    """[start, end) of the first normalised match of ``quote`` in ``passage_text``, in original offsets."""
    needle, _ = normalize(quote)
    if not needle:
        return None
    haystack, origin = normalize(passage_text)
    position = haystack.find(needle)
    if position < 0:
        return None
    return origin[position], origin[position + len(needle) - 1] + 1


def drops_negation(passage_text: str, start: int, end: int) -> bool:
    """True when the clause containing [start, end) has a negation before ``start`` that the quote omits."""
    quote = passage_text[start:end].casefold()
    if NEGATION.search(quote):
        return False
    sentence_start = 0
    for span in sentence_spans(passage_text, MAX_PASSAGE_CHARS):
        if span.start <= start < span.end:
            sentence_start = span.start
            break
    prefix = passage_text[sentence_start:start]
    clause = _CLAUSE_BREAK.split(prefix)[-1]
    return NEGATION.search(clause.casefold()) is not None


class CitationGuard:
    """Checks quotations against the passages retrieved for one claim in one request."""

    def __init__(self, documents: Sequence[ReferenceDocument], passages: Sequence[EvidencePassage]) -> None:
        by_id = {d.doc_id: d for d in documents}
        self.documents = by_id
        self.passages = {p.passage_id: p for p in passages}
        # Passages whose provenance does not check out against this request's documents.
        self.invalid_passages = {
            p.passage_id for p in passages if p.doc_id not in by_id or not p.matches(by_id[p.doc_id])
        }

    def check(self, passage_id: str | None, quote: str) -> Citation | GuardRejectionReason:
        """A Citation built from the passage's own text, or the reason the quotation is rejected."""
        passage = self.passages.get(passage_id) if passage_id is not None else None
        if passage is None:
            return GuardRejectionReason.UNKNOWN_PASSAGE
        if passage.passage_id in self.invalid_passages:
            return GuardRejectionReason.PASSAGE_PROVENANCE_INVALID
        located = find_quote(quote, passage.text)
        if located is None:
            return GuardRejectionReason.QUOTE_NOT_FOUND
        start, end = located
        if len(_WORD.findall(passage.text[start:end])) < MIN_QUOTE_WORDS:
            return GuardRejectionReason.QUOTE_TOO_SHORT
        if drops_negation(passage.text, start, end):
            return GuardRejectionReason.PARTIAL_QUOTE_DROPS_NEGATION
        citation = Citation(
            doc_id=passage.doc_id,
            doc_text_sha256=passage.doc_text_sha256,
            passage_id=passage.passage_id,
            quote=passage.text[start:end],
            quote_span=SourceSpan(start=passage.span.start + start, end=passage.span.start + end),
        )
        # Belt and braces: the citation must also match the original document, not just the passage.
        if not citation.matches(self.documents[passage.doc_id]):
            return GuardRejectionReason.PASSAGE_PROVENANCE_INVALID
        return citation


# --- Support checks: does the cited text actually carry the claim's figures? -------------------
#
# A verbatim quote proves the words exist, not that they support the claim. For a SUPPORTED
# answer, every figure the claim depends on must therefore appear in the cited quotes: each
# number with its unit, each date, and any qualifier the quotes put on a figure the claim
# repeats ("up to 12 hours" cannot support "12 hours"). CONTRADICTED answers are not checked
# this way: their figures differ from the evidence by definition.

_NUMBER = r"\d+(?:[.,]\d+)*"
_CURRENCY = {"\u20ac": "eur", "$": "usd", "\u00a3": "gbp"}
_UNITS = {
    "%": "percent", "percent": "percent", "per cent": "percent",
    "g": "gram", "gram": "gram", "grams": "gram", "kg": "kilogram", "kilogram": "kilogram", "kilograms": "kilogram",
    "mg": "milligram", "ml": "millilitre", "millilitre": "millilitre", "millilitres": "millilitre",
    "l": "litre", "litre": "litre", "litres": "litre", "liter": "litre", "liters": "litre",
    "h": "hour", "hr": "hour", "hrs": "hour", "hour": "hour", "hours": "hour",
    "min": "minute", "mins": "minute", "minute": "minute", "minutes": "minute",
    "day": "day", "days": "day", "week": "week", "weeks": "week", "month": "month", "months": "month",
    "year": "year", "years": "year", "mm": "millimetre", "cm": "centimetre", "km": "kilometre",
    "m": "metre", "metre": "metre", "metres": "metre", "meter": "metre", "meters": "metre",
    "lumen": "lumen", "lumens": "lumen", "w": "watt", "watts": "watt", "mah": "mah", "gb": "gigabyte", "tb": "terabyte",
}
_QUANTITY = re.compile(
    rf"(?P<cur>[\u20ac$\u00a3])?\s*(?P<num>{_NUMBER})(?:\s*-\s*|\s*)(?P<unit>per cent|%|[A-Za-z]+)?",
)
_DATE = re.compile(rf"\b(?:{_NUMBER}\s+)?({MONTHS.pattern[3:-3]})\b(?:\s+{_NUMBER})?", re.IGNORECASE)
_FIGURE_QUALIFIERS = ("up to", "about", "approximately", "around", "at least", "at most", "more than",
                      "less than", "fewer than", "nearly", "almost", "roughly", "as much as", "as many as")
_QUALIFIED = re.compile(
    rf"\b(?P<q>{'|'.join(re.escape(q) for q in _FIGURE_QUALIFIERS)})\s+[\u20ac$\u00a3]?\s*(?P<num>{_NUMBER})",
    re.IGNORECASE,
)


def _number(token: str) -> str:
    return token.replace(",", "")


def quantities(text: str) -> set[tuple[str, str | None]]:
    """(number, canonical unit or currency or None) for every number in ``text``."""
    found = set()
    for match in _QUANTITY.finditer(text):
        unit = _CURRENCY.get(match["cur"] or "")
        if unit is None and match["unit"]:
            unit = _UNITS.get(match["unit"].casefold())
        found.add((_number(match["num"]), unit))
    return found


def _dates(text: str) -> set[str]:
    """Month names that appear next to a day or year number (so the verb "may" is not a month)."""
    return {
        m.group(1).casefold()[:3]
        for m in _DATE.finditer(text)
        if re.search(r"\d", m.group(0))
    }


def support_problems(claim: str, quotes: list[str]) -> list[GuardRejectionReason]:
    """Why the cited quotes cannot carry a SUPPORTED verdict for ``claim``; empty if they can."""
    evidence = " ".join(quotes)
    problems = []
    claim_quantities, evidence_quantities = quantities(claim), quantities(evidence)
    evidence_units: dict[str, set[str | None]] = {}
    for number, unit in evidence_quantities:
        evidence_units.setdefault(number, set()).add(unit)
    for number, unit in claim_quantities:
        units = evidence_units.get(number)
        if units is None or (unit is not None and unit not in units and None not in units):
            problems.append(GuardRejectionReason.UNSUPPORTED_QUANTITY)
            break
    if not _dates(claim) <= _dates(evidence):
        problems.append(GuardRejectionReason.UNSUPPORTED_DATE)
    claim_cf, claim_numbers = claim.casefold(), {n for n, _ in claim_quantities}
    for match in _QUALIFIED.finditer(evidence):
        if _number(match["num"]) in claim_numbers and match["q"].casefold() not in claim_cf:
            problems.append(GuardRejectionReason.MISSING_QUALIFIER)
            break
    return problems
