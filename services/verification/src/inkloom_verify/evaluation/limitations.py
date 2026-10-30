"""Known limitations of the verification engine, shown in every evaluation report and in the
Trust Scorecard (EVAL.md Phase 8). One list, so the report and the UI cannot disagree.

Statuses:

* ``measured``: observed in a test or an evaluation run (``evidence`` names it);
* ``suspected``: likely from how the code works, not yet tested;
* ``unsupported``: the engine does not handle it by design;
* ``not_implemented``: planned work that does not exist yet.

A limitation is only ``measured`` when a test reproduces it (tests/test_known_limitations.py
pins each one, so a fix shows up as a failing test and this list is updated with it).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Limitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: str
    status: Literal["measured", "suspected", "unsupported", "not_implemented"]
    finding: str
    evidence: list[str] = []


LIMITATIONS: list[Limitation] = [
    Limitation(
        topic="Tables in PDFs",
        status="measured",
        finding="Text extraction (pypdf, backend) keeps a table's rows only when the PDF writes them row by row. "
        "For a column-ordered table every column comes out as a block, so a product loses its figures, and a "
        "model that pairs a product with the wrong row's figure gets a SUPPORTED the citation guard cannot refuse. "
        "Measured on one hand-built PDF of each kind; real PDFs vary.",
        evidence=[
            "tests/test_known_limitations.py::test_a_column_ordered_pdf_table_lets_a_wrong_product_figure_through",
            "tests/test_known_limitations.py::test_a_row_ordered_table_keeps_the_figure_with_its_product",
        ],
    ),
    Limitation(
        topic="Very long documents",
        status="measured",
        finding="A reference over 1,000,000 characters, or more than 50 references, is refused rather than truncated. "
        "On the 1,144-word product handbook, top-5 token-chunk retrieval keeps 100% recall but sends about 89% of "
        "the corpus to the verifier, so long documents cost more and expose the model to more look-alike facts.",
        evidence=[
            "tests/test_known_limitations.py::test_reference_documents_have_a_hard_size_limit",
            "EVAL.md: Retrieval phase: 200–400-token chunks",
        ],
    ),
    Limitation(
        topic="Non-English content",
        status="measured",
        finding="The negation check, retrieval stopwords and unit words are English only: a Portuguese claim that "
        "drops 'não' is not caught by the negation check. Prompts are English; a live model on other languages "
        "is untested, and the dataset is English only.",
        evidence=["tests/test_known_limitations.py::test_negation_is_only_detected_in_english"],
    ),
    Limitation(
        topic="Paraphrased evidence",
        status="measured",
        finding="Retrieval is lexical (BM25): a claim worded differently from its evidence ('cost €99' vs 'Price: €129') "
        "can retrieve nothing, and '12 hours' is not matched to 'twelve hours', so a correct claim is downgraded "
        "to NOT_ENOUGH_EVIDENCE (safe, but a missed confirmation).",
        evidence=[
            "tests/test_known_limitations.py::test_paraphrased_wording_can_defeat_lexical_retrieval",
            "tests/test_known_limitations.py::test_a_number_written_as_a_word_in_the_evidence_is_not_matched",
        ],
    ),
    Limitation(
        topic="Lexical guard heuristics",
        status="measured",
        finding="The property-binding (property_mismatch) and compound-claim (unsupported_clause) checks are "
        "lexical heuristics, not validated. They were tuned on the Round 3 step 03/04 matrix cases, the REG-014/015 "
        "tests and dev records v1-036/v1-045; of 12 probes checked afterwards, only 4 were written after the final "
        "rules, and one other probe shaped the rule for figures of different units. They are untested on fresh data "
        "until steps 06/07. Words match exactly: a synonym is accepted rather than checked ('stays chilled for up to "
        "12 hours' passes on 'cold for up to 24 hours and hot for up to 12 hours'), a correct claim worded like "
        "another unit's label can be falsely rejected ('a 2 year guarantee that covers the battery' next to "
        "'Battery life: up to 12 hours'), and a claim part paraphrased in new words can be refused. Two earlier "
        "limits, the elision swap and a part covered by one incidental shared word, are now caught.",
        evidence=[
            "tests/test_known_limitations.py::test_a_synonym_hides_a_figure_bound_to_another_property",
            "tests/test_known_limitations.py::test_a_claim_worded_like_another_units_label_can_be_falsely_rejected",
            "tests/test_guard_probes.py",
            "EVAL.md",
        ],
    ),
    Limitation(
        topic="Planted false facts in references",
        status="measured",
        finding="A false fact written as ordinary text in a reference is evidence like any other: only instructions "
        "aimed at a model are refused. References must be trusted when they are approved.",
        evidence=[
            "tests/test_prompt_security.py::test_an_instruction_worded_as_a_fact_is_not_recognised"
        ],
    ),
    Limitation(
        topic="Guard on a comparative claim across documents",
        status="measured",
        finding="The guard can reject a correct SUPPORTED answer whose claim compares figures that come from two "
        "documents. Held-out record v4-003 ('the Lantern's warranty is longer than the standard 2 year warranty', "
        "with the 3 year figure in one document and the 2 year figure in another) is rejected as property_mismatch "
        "even with the right gold quotes. It was found the first time the oracle ran on this fresh held-out record "
        "(2026-10-29), so the rule was deliberately not changed and the record was not replaced: held-out records "
        "do not steer the rules. It is a false rejection (a person reviews it), not a wrong approval.",
        evidence=["tests/test_eval_regressions.py::test_the_oracle_reproduces_every_gold_label"],
    ),
    Limitation(
        topic="Retrieval on a claim that carries an injected instruction",
        status="measured",
        finding="The retrieval-only evaluation uses the whole claim text as one query. On the 120-record dataset, "
        "2 of 87 records with evidence (v4-024 held-out, v4-040 dev) retrieve no passage, because the claim "
        "itself contains an injected instruction whose words dilute the query below the term-coverage threshold; "
        "the same claim without that sentence retrieves its passage. Recall@5 is 85/87 (was 37/37 on the "
        "80-record dataset), so the gate was re-measured, lower, because the dataset grew. The full pipeline "
        "extracts claims before retrieval and may avoid this; that is not measured until the live run.",
        evidence=[
            "tests/test_known_limitations.py::test_a_claim_that_carries_an_injected_instruction_retrieves_no_passage"
        ],
    ),
    Limitation(
        topic="Live model quality",
        status="measured",
        finding="One live run (google/gemini-2.5-flash-lite, verifier only, 80 synthetic claims, 25 held out) gave "
        "CONTRADICTED recall 87.5% (28/32), precision 90.3%, false-positive rate 6.2%, and citation validity "
        "86.7% (52/60), which misses the 100% gate; every quote was found verbatim (60/60). It is one run on "
        "AI-written labels (0/80 reviewed), so read it as an indication, not a guarantee; the full pipeline "
        "(extraction and routing) was not run live.",
        evidence=["EVAL.md"],
    ),
    Limitation(
        topic="Label review",
        status="measured",
        finding="Every label in eval/dataset.jsonl was written by an AI assistant and checked mechanically; none has "
        "been reviewed by a person (0/120). The data is synthetic (a fictional company) and small: one "
        "CONTRADICTED record is about 2 points of recall (1/49).",
        evidence=[
            "tests/test_dataset_validation.py::test_every_record_is_synthetic_and_unreviewed_and_says_so"
        ],
    ),
    Limitation(
        topic="Terminology and accessibility checks",
        status="measured",
        finding="Deterministic terminology, brand-compliance and accessibility rules exist (rules.py) and are unit "
        "tested, but they are not part of the labelled dataset, so this report says nothing about them. "
        "Accessibility checks read only Markdown/HTML in the submitted text and the metadata given: images, "
        "colours and media inside uploaded files are not inspected (those checks report not_checkable; the "
        "backend passes no ContentMetadata yet).",
        evidence=[
            "tests/test_rules_contract.py::test_one_check_record_per_rule_with_honest_statuses",
            "tests/test_rules_accessibility.py::test_no_images_anywhere_is_not_checkable_with_a_reason_about_uploaded_files",
        ],
    ),
    Limitation(
        topic="Visual and tone checks",
        status="unsupported",
        finding="Images themselves (logos, product photos), brand tone of voice and reading level are not checked; "
        "only all-caps and emoji runs are flagged as tone signals.",
        evidence=[],
    ),
    Limitation(
        topic="Backend review routing",
        status="unsupported",
        finding="The backend applies the engine's decision policy to every claim (services/api engine/pipeline.py, "
        "_with_decision_policy), so a weak or under-cited SUPPORTED claim goes to a person. This evaluation does not "
        "measure that routing: it is tested only by the backend suite (services/api/tests/test_decision_policy.py), "
        "which needs PostgreSQL and runs in CI. An earlier entry here said the backend routed on verdict != "
        "SUPPORTED only; that was out of date.",
        evidence=[],
    ),
]
