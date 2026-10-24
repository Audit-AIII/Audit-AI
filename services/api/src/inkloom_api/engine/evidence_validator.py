"""Phase 4: the backend never trusts the engine.

`inkloom_verify`'s own `CitationGuard` already checks a citation's quote against the passage the
model cited, inside the engine process. This module re-checks every citation again, from
scratch, against this backend's own copy of the source text (`CorpusEntry.document`, built from
`source_versions` rows this request already loaded) — independent of whatever the engine did
internally, so a bug or a future lower-trust code path on the engine side can't slip bad
evidence past us. "Independent" means: this code never reads the engine's own verdict on
whether a citation is valid, only the raw `doc_id` / `text_sha256` / `quote` / `quote_span`
values of the `Citation` itself.

Policy is strict, matching `CitationGuard`'s own stated policy (PROMPTS.md, "Citation guard"):
one rejected citation on a finding means none of that finding's citations are trusted, not just
the bad one — a result can't be partly backed by evidence we can't verify.
"""

from __future__ import annotations

import re
from enum import Enum

from inkloom_verify.schemas import Citation

from .corpus import CorpusEntry

_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


class IntegrityErrorCode(str, Enum):
    UNKNOWN_SOURCE = "unknown_source"  # doc_id/text_sha256 isn't in this review's approved corpus
    QUOTE_SPAN_OUT_OF_RANGE = "quote_span_out_of_range"
    QUOTE_NOT_FOUND = "quote_not_found"  # quote isn't the source text at that span, even normalised


class EvidenceIntegrityError(Exception):
    """One citation failed independent backend validation. `code` and `str(self)` are both
    safe to log and to store in an audit event: no document text, no model output."""

    def __init__(self, code: IntegrityErrorCode, citation: Citation) -> None:
        self.code = code
        self.citation = citation
        super().__init__(f"{code.value}: doc_id={citation.doc_id} passage_id={citation.passage_id}")


def validate_citation(
    citation: Citation, corpus_lookup: dict[tuple[str, str], CorpusEntry]
) -> CorpusEntry:
    """Returns the `CorpusEntry` the citation actually matches, or raises `EvidenceIntegrityError`.

    This is the one function that decides whether a citation may be saved as evidence. A source
    outside the approved corpus (wrong brand, wrong organisation, not approved, or simply never
    offered to the engine for this review) has no entry in `corpus_lookup` at all, so it is
    rejected by the same `UNKNOWN_SOURCE` path regardless of why it doesn't belong.
    """
    entry = corpus_lookup.get((citation.doc_id, citation.doc_text_sha256))
    if entry is None:
        raise EvidenceIntegrityError(IntegrityErrorCode.UNKNOWN_SOURCE, citation)

    source_text = entry.document.text
    start, end = citation.quote_span.start, citation.quote_span.end
    if not (0 <= start <= end <= len(source_text)):
        raise EvidenceIntegrityError(IntegrityErrorCode.QUOTE_SPAN_OUT_OF_RANGE, citation)

    excerpt = source_text[start:end]
    if _normalise(excerpt) != _normalise(citation.quote):
        raise EvidenceIntegrityError(IntegrityErrorCode.QUOTE_NOT_FOUND, citation)

    return entry


def validate_all(
    citations: list[Citation], corpus_lookup: dict[tuple[str, str], CorpusEntry]
) -> list[CorpusEntry]:
    """All-or-nothing: returns one `CorpusEntry` per citation, in order, or raises on the first
    failure. Callers should catch `EvidenceIntegrityError` and treat the whole finding as
    unverified rather than save any of its citations (see pipeline.py)."""
    return [validate_citation(citation, corpus_lookup) for citation in citations]
