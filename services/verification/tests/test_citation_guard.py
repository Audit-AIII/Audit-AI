from pathlib import Path

import pytest

from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.citation_guard import CitationGuard, drops_negation, find_quote, normalize
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import Citation, EvidencePassage, GuardRejectionReason, ReferenceDocument

R = GuardRejectionReason
SHEET = ReferenceDocument(
    doc_id="pods-fact-sheet",
    text=(
        "Battery life: up to 12 hours of playback per charge.\n"
        "Water resistance: IPX4 (splash resistant). Not suitable for swimming.\n"
        "Care: “hand wash” only.  The case is not dishwasher safe, and it weighs 48 g.\n"
    ),
)
OTHER = ReferenceDocument(doc_id="company-facts", text="Lumen Goods was founded in 2019 in Lisbon.")


def passages(*documents: ReferenceDocument) -> list[EvidencePassage]:
    retriever = BM25Retriever(list(documents), chunking=ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1))
    found = []
    for document in documents:
        for p in retriever.passages:
            if p.doc_id == document.doc_id:
                found.append(
                    EvidencePassage(
                        passage_id=p.passage_id, doc_id=p.doc_id, doc_text_sha256=p.doc_text_sha256,
                        span=p.span, text=p.text, retrieval={"method": "bm25", "score": 1.0, "rank": 1},
                    )
                )
    return found


@pytest.fixture
def sheet_passages():
    return passages(SHEET)


def passage_with(items, text):
    return next(p for p in items if text in p.text)


# --- Normalisation -----------------------------------------------------------------------------


def test_normalize_maps_back_to_original_offsets():
    text = "  A  “quoted”\n\tword  "
    normalized, origin = normalize(text)
    assert normalized == 'A "quoted" word'
    assert [text[i] for i in origin] == ["A", " ", "“", "q", "u", "o", "t", "e", "d", "”", "\n", "w", "o", "r", "d"]


def test_find_quote_tolerates_only_whitespace_and_quote_marks():
    text = 'Care: “hand wash” only.'
    assert find_quote('"hand wash" only', text) == (6, len(text) - 1)
    assert find_quote("Care:   “hand\nwash”", text) == (0, 17)
    assert find_quote("care: “hand wash”", text) is None  # case matters
    assert find_quote("hand-wash", text) is None  # punctuation matters
    assert find_quote("Care: ... only", text) is None  # no ellipses
    assert find_quote("   ", text) is None


# --- Accepted citations ------------------------------------------------------------------------


def test_valid_quote_becomes_a_verbatim_citation_in_document_coordinates(sheet_passages):
    passage = passage_with(sheet_passages, "Battery")
    citation = CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "up to 12 hours of playback")
    assert isinstance(citation, Citation)
    assert citation.quote == "up to 12 hours of playback"
    assert citation.matches(SHEET)
    assert SHEET.text[citation.quote_span.start : citation.quote_span.end] == citation.quote


def test_normalised_quote_is_stored_as_the_original_text(sheet_passages):
    passage = passage_with(sheet_passages, "Care")
    citation = CitationGuard([SHEET], sheet_passages).check(passage.passage_id, 'Care: "hand wash" only.')
    assert isinstance(citation, Citation)
    assert citation.quote == "Care: “hand wash” only."
    assert citation.matches(SHEET)


def test_quote_including_its_negation_is_accepted(sheet_passages):
    passage = passage_with(sheet_passages, "swimming")
    assert isinstance(CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "Not suitable for swimming."), Citation)


def test_negation_in_an_earlier_clause_does_not_block_a_quote(sheet_passages):
    passage = passage_with(sheet_passages, "dishwasher")
    citation = CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "it weighs 48 g")
    assert isinstance(citation, Citation)


# --- Rejected citations ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("needle", "quote", "reason"),
    [
        ("Battery", "up to 24 hours of playback", R.QUOTE_NOT_FOUND),  # fabricated number
        ("Battery", "up to 12 hours of playback per charge, guaranteed", R.QUOTE_NOT_FOUND),  # extended
        ("Battery", "up to 12 hours ... per charge", R.QUOTE_NOT_FOUND),  # stitched
        ("Battery", "Up to 12 hours of playback", R.QUOTE_NOT_FOUND),  # case changed
        ("Battery", "playback", R.QUOTE_TOO_SHORT),  # one word
        ("Battery", "12", R.QUOTE_TOO_SHORT),
        ("swimming", "suitable for swimming", R.PARTIAL_QUOTE_DROPS_NEGATION),  # partial quotation
        ("dishwasher", "dishwasher safe", R.PARTIAL_QUOTE_DROPS_NEGATION),
        ("dishwasher", "is not dishwasher safe, and it weighs 48 g. Lumen Goods", R.QUOTE_NOT_FOUND),
    ],
)
def test_rejected_quotes(sheet_passages, needle, quote, reason):
    passage = passage_with(sheet_passages, needle)
    assert CitationGuard([SHEET], sheet_passages).check(passage.passage_id, quote) == reason


def test_two_word_minimum_counts_numbers_as_words(sheet_passages):
    passage = passage_with(sheet_passages, "Battery")
    assert isinstance(CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "12 hours"), Citation)


def test_quote_from_an_unrelated_document_under_a_valid_label(sheet_passages):
    passage = passage_with(sheet_passages, "Battery")
    guard = CitationGuard([SHEET, OTHER], sheet_passages)
    assert guard.check(passage.passage_id, "founded in 2019 in Lisbon") == R.QUOTE_NOT_FOUND


def test_quote_from_a_passage_not_retrieved_for_this_claim():
    other_passage = passages(OTHER)[0]
    guard = CitationGuard([SHEET, OTHER], passages(SHEET))
    assert guard.check(other_passage.passage_id, "founded in 2019 in Lisbon") == R.UNKNOWN_PASSAGE
    assert guard.check(None, "anything at all") == R.UNKNOWN_PASSAGE


def test_quote_from_a_different_passage_of_the_same_document(sheet_passages):
    battery = passage_with(sheet_passages, "Battery")
    assert CitationGuard([SHEET], sheet_passages).check(battery.passage_id, "Not suitable for swimming.") == R.QUOTE_NOT_FOUND


@pytest.mark.parametrize(
    "documents",
    [
        [OTHER],  # passage's document is not in this request
        [ReferenceDocument(doc_id="pods-fact-sheet", text=SHEET.text.replace("12 hours", "24 hours"))],  # other version
    ],
)
def test_passage_provenance_must_match_the_request(sheet_passages, documents):
    guard = CitationGuard(documents, sheet_passages)
    passage = passage_with(sheet_passages, "Battery")
    assert passage.passage_id in guard.invalid_passages
    assert guard.check(passage.passage_id, "up to 12 hours of playback") == R.PASSAGE_PROVENANCE_INVALID


def test_tampered_passage_text_fails_provenance(sheet_passages):
    original = passage_with(sheet_passages, "Battery")
    forged_text = "Battery life: up to 24 hours of playback per charge."
    forged = original.model_copy(update={"text": forged_text})
    guard = CitationGuard([SHEET], [forged])
    assert guard.check(forged.passage_id, "up to 24 hours of playback") == R.PASSAGE_PROVENANCE_INVALID


def test_drops_negation_helper():
    text = "The case is not dishwasher safe, and it weighs 48 g."
    assert drops_negation(text, text.index("dishwasher"), text.index(","))
    assert not drops_negation(text, text.index("it weighs"), len(text) - 1)
    assert not drops_negation(text, text.index("not"), text.index(","))


# --- Dataset-wide check of the guard (deterministic; no model involved) ------------------------

DATASET = Path(__file__).resolve().parents[1] / "eval" / "data" / "verification_v1.jsonl"


def gold_cases():
    """(record, passage containing the gold quote, all passages, quote) for every gold quote."""
    for record in load_records(DATASET):
        retriever = BM25Retriever(record.references)
        all_passages = [
            EvidencePassage(
                passage_id=p.passage_id, doc_id=p.doc_id, doc_text_sha256=p.doc_text_sha256,
                span=p.span, text=p.text, retrieval={"method": "bm25", "score": 1.0, "rank": 1},
            )
            for p in retriever.passages
        ]
        for gold in record.gold_evidence:
            container = next(
                p for p in all_passages
                if p.doc_id == gold.doc_id and p.span.start <= gold.span.start and gold.span.end <= p.span.end
            )
            yield record, container, all_passages, gold.quote


def test_every_gold_quote_is_accepted_and_every_corruption_rejected():
    cases = list(gold_cases())
    assert len(cases) == 39
    for record, passage, all_passages, quote in cases:
        guard = CitationGuard(record.references, all_passages)
        accepted = guard.check(passage.passage_id, quote)
        assert isinstance(accepted, Citation) and accepted.quote == quote, (record.record_id, accepted)

        fabricated = quote + " (verified)"
        assert guard.check(passage.passage_id, fabricated) == R.QUOTE_NOT_FOUND, record.record_id
        wrong_label = next((p for p in all_passages if quote not in p.text), None)
        if wrong_label is not None:
            assert guard.check(wrong_label.passage_id, quote) == R.QUOTE_NOT_FOUND, record.record_id
        assert guard.check("psg_" + "0" * 24, quote) == R.UNKNOWN_PASSAGE
