"""Evidence validation (the backend never trusts the engine's citations):

1. Unknown source ID is rejected.                    -> test_unknown_source_is_rejected
2. Wrong-brand and cross-tenant source IDs rejected.
   -> test_source_from_a_different_corpus_is_rejected
3. Quote not in the passage is rejected.               -> test_quote_not_in_source_is_rejected
4. Valid quote with extra whitespace is accepted.
   -> test_quote_with_extra_whitespace_is_accepted
5. Draft source is never used as evidence.             -> covered end-to-end in test_reviews.py:
   `review_runner.latest_approved_sources` only ever selects `status == "approved"`, so a draft
   source's text can never reach `build_corpus` in the first place.

None of this needs a database: `validate_citation` only takes plain values (a `CorpusEntry`
built from a `ReferenceDocument`, and a `Citation`), independent of how either was stored.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from inkloom_verify.schemas import Citation, ReferenceDocument, SourceSpan

from inkloom_api.engine.corpus import CorpusEntry
from inkloom_api.engine.evidence_validator import (
    EvidenceIntegrityError,
    IntegrityErrorCode,
    validate_citation,
)

SOURCE_TEXT = "Body: 18/8 stainless steel with 70% recycled content."
_QUOTE = "70% recycled content"
_START = SOURCE_TEXT.index(_QUOTE)
_END = _START + len(_QUOTE)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(doc_id: str, text: str = SOURCE_TEXT) -> CorpusEntry:
    return CorpusEntry(
        brand_source_id=uuid.uuid4(),
        source_version_id=uuid.uuid4(),
        document=ReferenceDocument(doc_id=doc_id, text=text, text_sha256=_sha256(text)),
    )


def _citation(
    entry: CorpusEntry, start: int, end: int, quote: str, passage_id: str = "psg_test_0001"
) -> Citation:
    return Citation(
        doc_id=entry.document.doc_id,
        doc_text_sha256=entry.document.text_sha256,
        passage_id=passage_id,
        quote=quote,
        quote_span=SourceSpan(start=start, end=end),
    )


def test_unknown_source_is_rejected() -> None:
    entry = _entry("spec-sheet")
    citation = _citation(entry, _START, _END, _QUOTE)
    lookup: dict[tuple[str, str], CorpusEntry] = {}  # the corpus for this review has nothing in it

    with pytest.raises(EvidenceIntegrityError) as exc_info:
        validate_citation(citation, lookup)
    assert exc_info.value.code is IntegrityErrorCode.UNKNOWN_SOURCE


def test_source_from_a_different_corpus_is_rejected() -> None:
    """A citation naming a real, valid document that simply isn't part of THIS review's
    approved corpus (different brand, different organisation, or just never offered) is
    rejected the same way as a made-up doc_id — the lookup only ever contains this review's
    own approved sources."""
    other_organisations_entry = _entry("other-org-spec-sheet")
    this_reviews_corpus: dict[tuple[str, str], CorpusEntry] = {}  # does not include the entry above
    citation = _citation(other_organisations_entry, _START, _END, _QUOTE)

    with pytest.raises(EvidenceIntegrityError) as exc_info:
        validate_citation(citation, this_reviews_corpus)
    assert exc_info.value.code is IntegrityErrorCode.UNKNOWN_SOURCE


def test_quote_not_in_source_is_rejected() -> None:
    entry = _entry("spec-sheet")
    lookup = {(entry.document.doc_id, entry.document.text_sha256): entry}
    # Same span and length as the real quote, but different (fabricated) text.
    fabricated = "90% recycled content"
    assert len(fabricated) == len(_QUOTE)
    citation = _citation(entry, _START, _END, fabricated)

    with pytest.raises(EvidenceIntegrityError) as exc_info:
        validate_citation(citation, lookup)
    assert exc_info.value.code is IntegrityErrorCode.QUOTE_NOT_FOUND


def test_quote_with_extra_whitespace_is_accepted() -> None:
    """`Citation` itself enforces `len(quote) == quote_span.length` (schemas.py), so a quote can
    never literally be *longer* than its span - a legitimate whitespace difference is same-length
    but a different whitespace character (tab/newline in place of a space), which normalisation
    must still treat as equal to the source's plain single spaces (PROMPTS.md convention)."""
    entry = _entry("spec-sheet")
    lookup = {(entry.document.doc_id, entry.document.text_sha256): entry}
    same_length_different_whitespace = _QUOTE.replace(" ", "\t")
    assert len(same_length_different_whitespace) == len(_QUOTE)
    citation = _citation(entry, _START, _END, same_length_different_whitespace)

    result = validate_citation(citation, lookup)
    assert result is entry


def test_quote_span_out_of_range_is_rejected() -> None:
    entry = _entry("spec-sheet")
    lookup = {(entry.document.doc_id, entry.document.text_sha256): entry}
    # Same length as the source text, but shifted past the end of it.
    shift = 50
    citation = _citation(entry, shift, shift + len(SOURCE_TEXT), SOURCE_TEXT)

    with pytest.raises(EvidenceIntegrityError) as exc_info:
        validate_citation(citation, lookup)
    assert exc_info.value.code is IntegrityErrorCode.QUOTE_SPAN_OUT_OF_RANGE


def test_integrity_error_message_is_safe_to_log() -> None:
    """str(error) must never contain the source text or the quote - only ids and the code."""
    entry = _entry("spec-sheet")
    fabricated = "90% recycled content"
    citation = _citation(entry, _START, _END, fabricated)
    try:
        validate_citation(citation, {})
    except EvidenceIntegrityError as error:
        message = str(error)
        assert SOURCE_TEXT not in message
        assert fabricated not in message
        assert "spec-sheet" in message  # the doc_id itself is an opaque id, safe to log
