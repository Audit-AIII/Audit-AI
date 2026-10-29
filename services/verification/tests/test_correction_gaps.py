"""Round 3 step 05: correction-grounding gaps that still reproduce on main (gap table:
docs/round3/krish/corrections-gap-table.md).

A correction may delete the wrong figure instead of fixing it. The checks count dropped *units*
(drops_unit), so a figure with no unit ("4 colours", "40 employees", "3rd") can vanish with no
issue, and the re-check has no figure left to object to. Red until correction.py is fixed; the
cases that must still be offered pin the fix from the other side."""

import hashlib

import pytest

from inkloom_verify.correction import ClaimCorrector, CorrectionConfig, correction_issues
from inkloom_verify.evaluation.corrections import CorrectionCase, contradicted_result
from inkloom_verify.providers.fake import ScriptedProvider
from inkloom_verify.schemas import CorrectionIssueCode, CorrectionStatus, Verdict
from inkloom_verify.verification import ClaimVerifier

Issue = CorrectionIssueCode
COLOURS = ["Colours: 3 (Graphite, Sand, Teal)."]


def codes(original, replacement, quotes, before="", after=""):
    return [i.code for i in correction_issues(original, replacement, quotes, before, after)]


# --- Gap 3: a figure without a unit deleted instead of fixed --------------------------------------


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after"),
    [
        ("4 colours", "colours", COLOURS, "Lumen Pods come in ", "."),
        ("40 employees", "employees", ["Lumen Goods has 48 employees."], "Lumen Goods has ", "."),
        ("ranked 3rd", "ranked", ["Ranked 1st in 2025."], "Lumen Pods were ", " in 2025."),
    ],
    ids=["count", "headcount", "ordinal"],
)
def test_a_figure_deleted_instead_of_fixed_is_refused(original, replacement, quotes, before, after):
    found = codes(original, replacement, quotes, before, after)
    assert found and Issue.NO_CHANGE not in found


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after"),
    [
        # the figure fixed, not deleted
        ("4 colours", "3 colours", COLOURS, "Lumen Pods come in ", "."),
        ("40 employees", "48 employees", ["Lumen Goods has 48 employees."], "Lumen Goods has ", "."),
        # the wrong count replaced by the evidence's own list: nothing is lost
        ("4 colours", "Graphite, Sand and Teal", COLOURS, "Lumen Pods come in ", "."),
    ],
    ids=["count-fixed", "headcount-fixed", "count-to-list"],
)
def test_a_figure_fixed_or_replaced_by_the_evidence_is_still_offered(
    original, replacement, quotes, before, after
):
    assert codes(original, replacement, quotes, before, after) == []


# --- Through the corrector ------------------------------------------------------------------------

SHEET = "Lumen Pods - Fact Sheet\n\nColours: 3 (Graphite, Sand, Teal).\nWarranty: 2 years.\n"


def colours_case(sentence: str) -> CorrectionCase:
    quote = COLOURS[0]
    start = SHEET.index(quote)
    return CorrectionCase.model_validate(
        {
            "case_id": "gap-colours",
            "sentence": sentence,
            "references": [
                {
                    "doc_id": "pods-sheet",
                    "version": "v1",
                    "title": "Lumen Pods Fact Sheet",
                    "text": SHEET,
                    "text_sha256": hashlib.sha256(SHEET.encode()).hexdigest(),
                }
            ],
            "evidence": [
                {
                    "doc_id": "pods-sheet",
                    "span": {"start": start, "end": start + len(quote)},
                    "quote": quote,
                }
            ],
            "expected_outcome": "correctable",
            "reference_corrections": ["placeholder"],
            "rationale": "test case",
        }
    )


@pytest.mark.parametrize("recheck", [False, True])
def test_a_deleted_figure_is_refused_before_any_recheck(recheck):
    """Today it is proposed: with re-checking off, and after a SUPPORTED re-check, because
    "come in colours" has no figure left for the guard to check."""
    case = colours_case("Lumen Pods come in 4 colours.")
    result, content = contradicted_result(case)
    replies = [
        {
            "status": "corrected",
            "original_text": "4 colours",
            "replacement_text": "colours",
            "citations": ["C1"],
            "reason": "C1.",
        }
    ]
    if recheck:
        replies.append(
            {
                "verdict": "SUPPORTED",
                "citations": [{"passage": "P1", "quote": result.citations[0].quote}],
                "rationale": "P1.",
            }
        )
    provider = ScriptedProvider(*replies)
    verifier = ClaimVerifier(provider, case.references) if recheck else None
    corrected = ClaimCorrector(provider, verifier, CorrectionConfig(recheck=recheck)).correct(
        result, content
    )
    attempt = corrected.correction_attempt
    assert corrected.correction is None and attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    assert attempt.issues and len(provider.calls) == 1  # refused by the checks, no re-check asked
    assert corrected.verdict is Verdict.CONTRADICTED and corrected.requires_human_review
