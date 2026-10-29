"""EVAL.md Phase 8: the known limitations shown in reports and the Trust Scorecard, pinned as
tests so that "measured" means measured. Each test asserts today's *limited* behaviour: if a fix
lands, the test fails and the limitation entry (evaluation/limitations.py) must be updated."""

import pytest
from pydantic import ValidationError

from e2e_support import RoutedProvider, data_block
from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.citation_guard import support_problems
from inkloom_verify.evaluation.limitations import LIMITATIONS
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import (
    MAX_REFERENCE_CHARS,
    ReferenceDocument,
    Verdict,
)
from inkloom_verify.schemas import (
    GuardRejectionReason as R,
)
from inkloom_verify.verification import ClaimVerifier, VerificationConfig, verify_claim

# Exact pypdf 5.9.0 output for a hand-built PDF whose 3x3 table is written column by column
# (scratch probe, EVAL.md Phase 8): each column comes out as a block, so rows are lost.
COLUMN_ORDERED = "Product\nLumen Pods\nLumen Bottle\nWeight\n5.2 g\n340 g\nPrice\n129 EUR\n39 EUR"
# The same table written row by row: pypdf keeps each row on one line.
ROW_ORDERED = "Product Weight Price\nLumen Pods 5.2 g 129 EUR\nLumen Bottle 340 g 39 EUR"


def verify(claim_text: str, document_text: str, verdict: str, quote: str):
    doc = ReferenceDocument(doc_id="table-sheet", text=document_text)

    def respond(call):
        passages = data_block(call, "verification_input_json")["passages"]
        label = next((p["label"] for p in passages if quote in p["text"]), "P1")
        return {
            "verdict": verdict,
            "citations": [{"passage": label, "quote": quote}],
            "rationale": "x",
        }

    claim = {
        "claim_id": "clm_0001",
        "text": claim_text,
        "source_span": {"start": 0, "end": len(claim_text)},
    }
    return verify_claim(
        claim,
        BM25Retriever([doc]),
        ClaimVerifier(RoutedProvider(respond), [doc], VerificationConfig()),
    )


def test_a_column_ordered_pdf_table_lets_a_wrong_product_figure_through():
    """MEASURED: with the column-flattened text, a model that pairs the bottle with the Pods'
    weight gets a SUPPORTED the guard cannot refuse: '5.2 g' is a real quote, its figure matches,
    and the leading product name is not checked."""
    result = verify("The Lumen Bottle weighs 5.2 g.", COLUMN_ORDERED, "SUPPORTED", "Weight\n5.2 g")
    assert result.verdict is Verdict.SUPPORTED


def test_a_row_ordered_table_keeps_the_figure_with_its_product():
    result = verify(
        "The Lumen Bottle weighs 5.2 g.", ROW_ORDERED, "SUPPORTED", "Lumen Bottle 340 g 39 EUR"
    )
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE
    assert [r.reason for r in result.citation_guard.rejected] == [R.UNSUPPORTED_QUANTITY]


def test_negation_is_only_detected_in_english():
    """MEASURED: the negation check knows English negations only."""
    assert support_problems(
        "The bottle is dishwasher safe.", ["The bottle is not dishwasher safe."]
    ) == [R.NEGATION_MISMATCH]
    assert (
        support_problems(
            "A garrafa pode ir à máquina de lavar.", ["A garrafa não pode ir à máquina de lavar."]
        )
        == []
    )


def test_a_number_written_as_a_word_in_the_evidence_is_not_matched():
    """MEASURED: '12 hours' is not matched to 'twelve hours'; a correct SUPPORTED is downgraded
    (safe, but a missed confirmation)."""
    assert support_problems(
        "Lumen Pods play for 12 hours.", ["Lumen Pods play for twelve hours."]
    ) == [R.UNSUPPORTED_QUANTITY]


def test_paraphrased_wording_can_defeat_lexical_retrieval():
    """MEASURED (REG-004): 'cost €99' shares no word with 'Price: €129', so sentence-window
    retrieval offers the model no evidence at all."""
    doc = ReferenceDocument(
        doc_id="sheet", text="Weight: 5.2 g per earbud.\nPrice: €129 (EU launch price).\n"
    )
    retriever = BM25Retriever(
        [doc], chunking=ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1)
    )
    claim = {
        "claim_id": "clm_0001",
        "text": "Lumen Pods cost €99.",
        "source_span": {"start": 0, "end": 20},
    }
    assert not any("Price" in p.text for p in retriever.retrieve(claim))


def test_a_synonym_hides_a_figure_bound_to_another_property():
    """MEASURED: the binding rules match words exactly, so "chilled" is neither "cold" nor "hot"
    and the hot figure is accepted for a cold claim. Synonyms are accepted, not checked."""
    quote = "keeps drinks cold for up to 24 hours and hot for up to 12 hours"
    assert support_problems("The bottle stays chilled for up to 12 hours.", [quote]) == []


def test_a_claim_worded_like_another_units_label_can_be_falsely_rejected():
    """MEASURED: the 2 years are the warranty, and a guarantee that covers the battery is that
    warranty; but "guarantee" is not "warranty" and "battery" is the 12-hour figure's label, so a
    correct claim is refused (property_mismatch)."""
    quotes = ["Warranty: 2 years.", "Battery life: up to 12 hours per charge."]
    claim = "Lumen Pods come with a 2 year guarantee that covers the battery."
    assert support_problems(claim, quotes) == [R.PROPERTY_MISMATCH]


def test_reference_documents_have_a_hard_size_limit():
    """MEASURED: a reference over 1,000,000 characters is refused, not truncated."""
    ReferenceDocument(doc_id="max", text="a" * MAX_REFERENCE_CHARS)
    with pytest.raises(ValidationError):
        ReferenceDocument(doc_id="over", text="a" * (MAX_REFERENCE_CHARS + 1))


def test_every_limitation_names_its_status_and_evidence():
    assert {entry.status for entry in LIMITATIONS} <= {
        "measured",
        "suspected",
        "unsupported",
        "not_implemented",
    }
    topics = {entry.topic for entry in LIMITATIONS}
    assert {
        "Tables in PDFs",
        "Very long documents",
        "Non-English content",
        "Paraphrased evidence",
    } <= topics
    for entry in LIMITATIONS:
        if entry.status == "measured":
            assert entry.evidence and all(
                e.startswith("tests/") or e.startswith("EVAL.md") for e in entry.evidence
            ), entry.topic
