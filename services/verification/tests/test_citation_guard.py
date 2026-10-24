from pathlib import Path

import pytest

from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.citation_guard import (
    CitationGuard,
    conflicting_passage,
    drops_negation,
    find_quote,
    names,
    normalize,
    support_problems,
)
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import (
    Citation,
    EvidencePassage,
    GuardRejectionReason,
    ReferenceDocument,
)

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
    retriever = BM25Retriever(
        list(documents),
        chunking=ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1),
    )
    found = []
    for document in documents:
        for p in retriever.passages:
            if p.doc_id == document.doc_id:
                found.append(
                    EvidencePassage(
                        passage_id=p.passage_id,
                        doc_id=p.doc_id,
                        doc_text_sha256=p.doc_text_sha256,
                        span=p.span,
                        text=p.text,
                        retrieval={"method": "bm25", "score": 1.0, "rank": 1},
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
    assert [text[i] for i in origin] == [
        "A",
        " ",
        "“",
        "q",
        "u",
        "o",
        "t",
        "e",
        "d",
        "”",
        "\n",
        "w",
        "o",
        "r",
        "d",
    ]


def test_find_quote_tolerates_only_whitespace_and_quote_marks():
    text = "Care: “hand wash” only."
    assert find_quote('"hand wash" only', text) == (6, len(text) - 1)
    assert find_quote("Care:   “hand\nwash”", text) == (0, 17)
    assert find_quote("care: “hand wash”", text) is None  # case matters
    assert find_quote("hand-wash", text) is None  # punctuation matters
    assert find_quote("Care: ... only", text) is None  # no ellipses
    assert find_quote("   ", text) is None


# --- Accepted citations ------------------------------------------------------------------------


def test_valid_quote_becomes_a_verbatim_citation_in_document_coordinates(sheet_passages):
    passage = passage_with(sheet_passages, "Battery")
    citation = CitationGuard([SHEET], sheet_passages).check(
        passage.passage_id, "up to 12 hours of playback"
    )
    assert isinstance(citation, Citation)
    assert citation.quote == "up to 12 hours of playback"
    assert citation.matches(SHEET)
    assert SHEET.text[citation.quote_span.start : citation.quote_span.end] == citation.quote


def test_normalised_quote_is_stored_as_the_original_text(sheet_passages):
    passage = passage_with(sheet_passages, "Care")
    citation = CitationGuard([SHEET], sheet_passages).check(
        passage.passage_id, 'Care: "hand wash" only.'
    )
    assert isinstance(citation, Citation)
    assert citation.quote == "Care: “hand wash” only."
    assert citation.matches(SHEET)


def test_quote_including_its_negation_is_accepted(sheet_passages):
    passage = passage_with(sheet_passages, "swimming")
    assert isinstance(
        CitationGuard([SHEET], sheet_passages).check(
            passage.passage_id, "Not suitable for swimming."
        ),
        Citation,
    )


def test_negation_in_an_earlier_clause_does_not_block_a_quote(sheet_passages):
    passage = passage_with(sheet_passages, "dishwasher")
    citation = CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "it weighs 48 g")
    assert isinstance(citation, Citation)


# --- Rejected citations ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("needle", "quote", "reason"),
    [
        ("Battery", "up to 24 hours of playback", R.QUOTE_NOT_FOUND),  # fabricated number
        (
            "Battery",
            "up to 12 hours of playback per charge, guaranteed",
            R.QUOTE_NOT_FOUND,
        ),  # extended
        ("Battery", "up to 12 hours ... per charge", R.QUOTE_NOT_FOUND),  # stitched
        ("Battery", "Up to 12 hours of playback", R.QUOTE_NOT_FOUND),  # case changed
        ("Battery", "playback", R.QUOTE_TOO_SHORT),  # one word
        ("Battery", "12", R.QUOTE_TOO_SHORT),
        ("swimming", "suitable for swimming", R.PARTIAL_QUOTE_DROPS_NEGATION),  # partial quotation
        ("dishwasher", "dishwasher safe", R.PARTIAL_QUOTE_DROPS_NEGATION),
        (
            "dishwasher",
            "is not dishwasher safe, and it weighs 48 g. Lumen Goods",
            R.QUOTE_NOT_FOUND,
        ),
        # Phase 4 near-matches: one changed unit, weight, or negation must not match.
        ("Battery", "up to 12 minutes of playback per charge", R.QUOTE_NOT_FOUND),  # changed unit
        ("dishwasher", "it weighs 84 g", R.QUOTE_NOT_FOUND),  # transposed digits
        (
            "dishwasher",
            "The case is dishwasher safe",
            R.QUOTE_NOT_FOUND,
        ),  # negation removed inside the quote
        (
            "Battery",
            "up to 12 hours of no playback per charge",
            R.QUOTE_NOT_FOUND,
        ),  # negation inserted
    ],
)
def test_rejected_quotes(sheet_passages, needle, quote, reason):
    passage = passage_with(sheet_passages, needle)
    assert CitationGuard([SHEET], sheet_passages).check(passage.passage_id, quote) == reason


def test_two_word_minimum_counts_numbers_as_words(sheet_passages):
    passage = passage_with(sheet_passages, "Battery")
    assert isinstance(
        CitationGuard([SHEET], sheet_passages).check(passage.passage_id, "12 hours"), Citation
    )


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
    assert (
        CitationGuard([SHEET], sheet_passages).check(
            battery.passage_id, "Not suitable for swimming."
        )
        == R.QUOTE_NOT_FOUND
    )


@pytest.mark.parametrize(
    "documents",
    [
        [OTHER],  # passage's document is not in this request
        [
            ReferenceDocument(
                doc_id="pods-fact-sheet", text=SHEET.text.replace("12 hours", "24 hours")
            )
        ],  # other version
    ],
)
def test_passage_provenance_must_match_the_request(sheet_passages, documents):
    guard = CitationGuard(documents, sheet_passages)
    passage = passage_with(sheet_passages, "Battery")
    assert passage.passage_id in guard.invalid_passages
    assert (
        guard.check(passage.passage_id, "up to 12 hours of playback")
        == R.PASSAGE_PROVENANCE_INVALID
    )


def test_tampered_passage_text_fails_provenance(sheet_passages):
    original = passage_with(sheet_passages, "Battery")
    forged_text = "Battery life: up to 24 hours of playback per charge."
    forged = original.model_copy(update={"text": forged_text})
    guard = CitationGuard([SHEET], [forged])
    assert (
        guard.check(forged.passage_id, "up to 24 hours of playback") == R.PASSAGE_PROVENANCE_INVALID
    )


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
                passage_id=p.passage_id,
                doc_id=p.doc_id,
                doc_text_sha256=p.doc_text_sha256,
                span=p.span,
                text=p.text,
                retrieval={"method": "bm25", "score": 1.0, "rank": 1},
            )
            for p in retriever.passages
        ]
        for gold in record.gold_evidence:
            container = next(
                p
                for p in all_passages
                if p.doc_id == gold.doc_id
                and p.span.start <= gold.span.start
                and gold.span.end <= p.span.end
            )
            yield record, container, all_passages, gold.quote


def test_every_gold_quote_is_accepted_and_every_corruption_rejected():
    cases = list(gold_cases())
    assert len(cases) == 39
    for record, passage, all_passages, quote in cases:
        guard = CitationGuard(record.references, all_passages)
        accepted = guard.check(passage.passage_id, quote)
        assert isinstance(accepted, Citation) and accepted.quote == quote, (
            record.record_id,
            accepted,
        )

        fabricated = quote + " (verified)"
        assert guard.check(passage.passage_id, fabricated) == R.QUOTE_NOT_FOUND, record.record_id
        wrong_label = next((p for p in all_passages if quote not in p.text), None)
        if wrong_label is not None:
            assert guard.check(wrong_label.passage_id, quote) == R.QUOTE_NOT_FOUND, record.record_id
        assert guard.check("psg_" + "0" * 24, quote) == R.UNKNOWN_PASSAGE


# --- Support checks: valid quotes must also carry the claim's figures -------------------------

from inkloom_verify.citation_guard import quantities  # noqa: E402


@pytest.mark.parametrize(
    ("claim", "quote", "expected"),
    [
        ("Pods offer up to 12 hours of playback.", "up to 12 hours of playback per charge", []),
        (
            "Pods offer 24 hours of playback.",
            "up to 12 hours of playback per charge",
            [R.UNSUPPORTED_QUANTITY],
        ),  # numeric conflict
        (
            "Pods offer 12 hours of playback.",
            "up to 12 hours of playback per charge",
            [R.MISSING_QUALIFIER],
        ),
        (
            "The lamp weighs 1100 grams.",
            "The Lumen Lamp weighs 1100 g.",
            [],
        ),  # same unit, other spelling
        ("The bottle holds 750 l.", "Capacity: 750 ml.", [R.UNSUPPORTED_QUANTITY]),  # unit conflict
        (
            "Pods cost $129.",
            "Price: \u20ac129 (EU launch price).",
            [R.UNSUPPORTED_QUANTITY],
        ),  # currency conflict
        ("Pods cost \u20ac129.", "Price: \u20ac129 (EU launch price).", []),
        (
            "Pods launch on 2 May 2026.",
            "Launch date: 2 April 2026",
            [R.UNSUPPORTED_DATE],
        ),  # date conflict
        ("Pods launch on 2 April 2026.", "Launch date: 2 April 2026", []),
        (
            "Lumen was founded in 2015.",
            "Lumen Goods was founded in 2019",
            [R.UNSUPPORTED_QUANTITY],
        ),  # year conflict
        ("The bottle may be hand washed.", "Care: hand wash only.", []),  # "may" is not a month
        ("The bottle is 70% recycled steel.", "70% recycled stainless steel", []),
        (
            "The bottle is 90% recycled steel.",
            "70% recycled stainless steel",
            [R.UNSUPPORTED_QUANTITY],
        ),
    ],
)
def test_support_problems(claim, quote, expected):
    assert support_problems(claim, [quote]) == expected


def test_figures_may_come_from_any_cited_quote():
    quotes = ["Colours: Graphite, Sand, Teal.", "Price: \u20ac129 (EU launch price)."]
    assert support_problems("Pods come in Teal and cost \u20ac129.", quotes) == []


def test_quantities_normalise_units_and_separators():
    assert quantities("1,200 mAh, 5.2 g, 70%, \u20ac39, 24-hour") == {
        ("1200", "mah"),
        ("5.2", "gram"),
        ("70", "percent"),
        ("39", "eur"),
        ("24", "hour"),
    }


# --- Phase 4: dates near-match, names and conflicting evidence -----------------------------------

LAUNCH = ReferenceDocument(doc_id="launch-plan", text="Launch date: 2 April 2026 in the EU.")


def test_a_changed_date_is_not_the_same_quote():
    items = passages(LAUNCH)
    guard = CitationGuard([LAUNCH], items)
    assert isinstance(guard.check(items[0].passage_id, "Launch date: 2 April 2026"), Citation)
    for changed in (
        "Launch date: 12 April 2026",
        "Launch date: 2 May 2026",
        "Launch date: 2 April 2025",
    ):
        assert guard.check(items[0].passage_id, changed) is R.QUOTE_NOT_FOUND


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        (
            "Lumen Goods was founded in 2019 in Lisbon.",
            {"Lisbon"},
        ),  # the subject run is not a name to check
        ("The Lumen Pods weigh 5 g.", set()),
        ("Ana Ribeiro is the CEO of Lumen Goods.", {"Lumen", "Goods"}),  # acronym skipped
        ("Pods launch on 2 April 2026 in Porto.", {"Porto"}),  # month skipped
        ("it ships with a USB-C cable.", set()),
    ],
)
def test_names_skips_the_subject_months_and_acronyms(claim, expected):
    assert names(claim) == expected


def test_an_added_name_is_unsupported_even_with_a_valid_quote():
    quote, passage = "founded in 2019", OTHER.text
    assert support_problems("Lumen Goods was founded in 2019 in Lisbon.", [quote], [passage]) == []
    assert support_problems("Lumen Goods was founded in 2019 in Porto.", [quote], [passage]) == [
        R.UNSUPPORTED_NAME
    ]
    assert (
        support_problems("Lumen Goods was founded in 2019 in Porto.", [quote]) == []
    )  # names need the passages


def evidence(*documents: ReferenceDocument) -> list[EvidencePassage]:
    return passages(*documents)


FACT_SHEET = ReferenceDocument(
    doc_id="pods-fact-sheet",
    text="Battery life: up to 12 hours of playback per charge.\nPrice: €129 in the EU.",
)
UPDATE_NOTE = ReferenceDocument(
    doc_id="pods-update-note",
    text="After the firmware update, battery life is up to 14 hours of playback per charge.",
)
PRICE_LIST = ReferenceDocument(
    doc_id="retail-price-list", text="Retail price list Q2: Lumen Pods €119 in the EU."
)
PRESS = ReferenceDocument(
    doc_id="press-release-draft", text="Lumen Pods launch on 16 April 2026 across the EU."
)
BOTTLE = ReferenceDocument(
    doc_id="bottle-sheet", text="The bottle keeps drinks cold for up to 24 hours."
)


@pytest.mark.parametrize(
    ("claim", "documents", "conflicting_doc"),
    [
        (
            "Lumen Pods offer up to 12 hours of playback per charge.",
            (FACT_SHEET, UPDATE_NOTE),
            "pods-update-note",
        ),
        ("Lumen Pods cost €129 in the EU.", (FACT_SHEET, PRICE_LIST), "retail-price-list"),
        (
            "Lumen Pods launch on 2 April 2026 across the EU.",
            (LAUNCH, PRESS),
            "press-release-draft",
        ),
    ],
)
def test_documents_disagreeing_about_the_claims_figure_are_a_conflict(
    claim, documents, conflicting_doc
):
    found = conflicting_passage(claim, evidence(*documents))
    assert found is not None and found.doc_id == conflicting_doc


@pytest.mark.parametrize(
    ("claim", "documents", "why"),
    [
        (
            "Lumen Pods offer up to 12 hours of playback per charge.",
            (FACT_SHEET, BOTTLE),
            "different topic, same unit",
        ),
        (
            "Lumen Pods cost €99 in the EU.",
            (FACT_SHEET, PRICE_LIST),
            "no document backs the claim: a plain contradiction",
        ),
        (
            "Lumen Pods offer up to 12 hours of playback per charge.",
            (FACT_SHEET,),
            "one document only",
        ),
        (
            "Lumen Pods offer long battery life.",
            (FACT_SHEET, UPDATE_NOTE),
            "no figure in the claim",
        ),
        (
            "The bottle keeps drinks cold for up to 24 hours.",
            (BOTTLE, UPDATE_NOTE),
            "the other figure is about something else",
        ),
    ],
)
def test_no_conflict(claim, documents, why):
    assert conflicting_passage(claim, evidence(*documents)) is None, why


def test_a_different_value_inside_the_same_document_is_not_a_cross_source_conflict():
    both = ReferenceDocument(
        doc_id="pods-faq",
        text="Battery: up to 12 hours of playback per charge. With ANC on, up to 9 hours of playback per charge.",
    )
    assert (
        conflicting_passage(
            "Lumen Pods offer up to 12 hours of playback per charge.", evidence(both)
        )
        is None
    )


def test_regression_live_run_a_seconds_claim_is_not_supported_by_a_minutes_quote():
    """Found by the live evaluation of 2026-10-24 (record v3-012, xingchen-agi/xing4.0-29b-a4b:free):
    "second" was not a known unit, so "10-second" matched the quote's "10-minute"."""
    from inkloom_verify.citation_guard import quantities, support_problems

    assert ("10", "second") in quantities("A 10-second charge gives up to 2 hours")
    claim = "A 10-second charge gives Lumen Pods up to 2 hours of playback."
    quote = "A 10-minute charge gives up to 2 hours of playback."
    passage = "Lumen Pods - Product Fact Sheet. Charging: USB-C. " + quote
    assert support_problems(claim, [quote], [passage]) == [
        GuardRejectionReason.UNSUPPORTED_QUANTITY
    ]
    same = "A 10-minute charge gives Lumen Pods up to 2 hours of playback."
    assert support_problems(same, [quote], [passage]) == []
