"""Round 3 Phase 5: a proposed correction is not evidence of its own truth.

The correction checks already refuse a figure, date or name that the cited quotes do not give. They
did not ask *which property* the quotes give a figure for, or whether a rewritten clause is in the
evidence at all. These tests cover both, deterministically and through the corrector with and
without the re-check, and pin the corrections that must still be offered."""

import hashlib

import pytest

from inkloom_verify.correction import ClaimCorrector, CorrectionConfig, correction_issues
from inkloom_verify.evaluation.corrections import CorrectionCase, contradicted_result
from inkloom_verify.providers.fake import ScriptedProvider
from inkloom_verify.schemas import (
    ClaimResult,
    CorrectionIssueCode,
    CorrectionStatus,
    GuardRejectionReason,
    Verdict,
)
from inkloom_verify.verification import ClaimVerifier

Issue = CorrectionIssueCode
# Two values of one unit for two properties: the shape that lets a figure be borrowed.
FLASK = ["Keeps drinks cold for up to 24 hours and hot for up to 12 hours."]
BATTERY = ["Battery: up to 8 hours per earbud, up to 36 hours with the charging case."]
CHARGING = ["Charging: USB-C.", "Weight: 5.2 g per earbud; charging case 48 g."]


def codes(original, replacement, quotes, before="", after="", passages=()):
    extra = {"passages": list(passages)} if passages else {}
    return [
        i.code for i in correction_issues(original, replacement, quotes, before, after, **extra)
    ]


# --- A figure the evidence gives for another property ---------------------------------------------


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after"),
    [
        # the cold figure offered for "hot"
        ("6 hours", "24 hours", FLASK, "Keeps drinks hot for up to ", "."),
        ("6", "24", FLASK, "Keeps drinks hot for up to ", " hours."),  # unit outside the target
        # the charging-case figure offered for one earbud
        ("12 hours", "36 hours", BATTERY, "Each earbud plays for up to ", " per charge."),
        # a rewrite that binds both figures to the wrong property
        (
            "24 hours and hot for up to 6 hours",
            "12 hours and hot for up to 24 hours",
            FLASK,
            "Keeps drinks cold for up to ",
            ".",
        ),
    ],
    ids=["hot-gets-cold", "number-only", "earbud-gets-case", "rewrite-swaps"],
)
def test_a_figure_bound_to_another_property_is_an_unsupported_addition(
    original, replacement, quotes, before, after
):
    assert codes(original, replacement, quotes, before, after) == [Issue.UNSUPPORTED_ADDITION]


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after"),
    [
        ("6 hours", "12 hours", FLASK, "Keeps drinks hot for up to ", "."),
        ("6", "12", FLASK, "Keeps drinks hot for up to ", " hours."),
        ("12 hours", "8 hours", BATTERY, "Each earbud plays for up to ", " per charge."),
        ("12 hours", "36 hours", BATTERY, "With the charging case they play for up to ", "."),
        # the swap that puts both figures back where the evidence has them
        (
            "12 hours and hot for up to 24 hours",
            "24 hours and hot for up to 12 hours",
            FLASK,
            "Keeps drinks cold for up to ",
            ".",
        ),
        # one value of the unit in the quotes: nothing to confuse it with, never re-read
        ("7 g", "5.2 g", ["Weight: 5.2 g per earbud"], "They weigh ", " each."),
    ],
    ids=["hot", "hot-number-only", "earbud", "case", "swap-fixed", "single-value"],
)
def test_a_figure_bound_to_the_claims_property_is_still_offered(
    original, replacement, quotes, before, after
):
    assert codes(original, replacement, quotes, before, after) == []


# --- A rewritten clause that is in none of the evidence -------------------------------------------


def test_a_rewrite_that_restates_an_unsupported_part_is_an_unsupported_addition():
    """Every word the edit adds is in the quotes ("USB-C"), but the rewrite also restates a part
    the evidence never mentions."""
    found = correction_issues(
        "charge over micro-USB and include a wireless charging pad",
        "charge over USB-C and include a wireless charging pad",
        CHARGING,
        "The earbuds ",
        ".",
    )
    assert [i.code for i in found] == [Issue.UNSUPPORTED_ADDITION]
    assert "wireless charging pad" in found[0].detail


@pytest.mark.parametrize(
    ("original", "replacement", "quotes", "before", "after", "passages"),
    [
        # every part of the rewrite is in the quotes
        (
            "charge over micro-USB and weigh 7 g",
            "charge over USB-C and weigh 5.2 g",
            CHARGING,
            "The earbuds ",
            " per earbud.",
            (),
        ),
        # a part given by the cited passage, not by the quote
        (
            "are waterproof and ship in May",
            "are splash resistant and ship in May",
            ["Water resistance: IPX4 (splash resistant)."],
            "The earbuds ",
            ".",
            ["Water resistance: IPX4 (splash resistant). Orders ship in May."],
        ),
        # a narrow edit: the untouched part is not the correction's statement (re-check judges it)
        (
            "micro-USB",
            "USB-C",
            CHARGING,
            "The earbuds charge over ",
            " and include a wireless charging pad.",
            (),
        ),
        # a part reworded from the original's own words ("not safe" for "not suitable")
        (
            "waterproof and safe for swimming",
            "splash resistant and not safe for swimming",
            ["Water resistance: IPX4 (splash resistant). Not suitable for swimming."],
            "The earbuds are ",
            ".",
            (),
        ),
    ],
    ids=["all-parts-quoted", "part-in-passage", "narrow-edit", "paraphrase"],
)
def test_a_rewrite_whose_parts_are_in_the_evidence_is_still_offered(
    original, replacement, quotes, before, after, passages
):
    assert codes(original, replacement, quotes, before, after, passages) == []


def test_words_added_beside_a_fix_are_still_refused():
    """Existing behaviour: a new clause's words must be in the quotes."""
    found = codes("micro-USB", "USB-C and a wireless pad", CHARGING, "Charges over ", ".")
    assert Issue.UNSUPPORTED_ADDITION in found


# --- Through the corrector ------------------------------------------------------------------------

SHEET = (
    "Trail Flask - Fact Sheet\n\n"
    "Insulation: keeps drinks cold for up to 24 hours and hot for up to 12 hours.\n"
    "Capacity: 750 ml.\nCharging: none.\n"
)


def flask_case(sentence: str) -> CorrectionCase:
    quote = FLASK[0][0].lower() + FLASK[0][1:]
    start = SHEET.index(quote)
    return CorrectionCase.model_validate(
        {
            "case_id": "grounding-flask",
            "sentence": sentence,
            "references": [
                {
                    "doc_id": "flask-sheet",
                    "version": "v1",
                    "title": "Trail Flask Fact Sheet",
                    "text": SHEET,
                    "text_sha256": hashlib.sha256(SHEET.encode()).hexdigest(),
                }
            ],
            "evidence": [
                {
                    "doc_id": "flask-sheet",
                    "span": {"start": start, "end": start + len(quote)},
                    "quote": quote,
                }
            ],
            "expected_outcome": "correctable",
            "reference_corrections": ["placeholder"],
            "rationale": "test case",
        }
    )


def run(sentence, original, replacement, *recheck_replies, recheck=True):
    case = flask_case(sentence)
    result, content = contradicted_result(case)
    provider = ScriptedProvider(
        {
            "status": "corrected",
            "original_text": original,
            "replacement_text": replacement,
            "citations": ["C1"],
            "reason": "C1.",
        },
        *recheck_replies,
    )
    verifier = ClaimVerifier(provider, case.references) if recheck else None
    corrected = ClaimCorrector(provider, verifier, CorrectionConfig(recheck=recheck)).correct(
        result, content
    )
    ClaimResult.model_validate(corrected.model_dump())
    return corrected, provider, result


def supported_by(result):
    return {
        "verdict": "SUPPORTED",
        "citations": [{"passage": "P1", "quote": result.citations[0].quote}],
        "rationale": "P1.",
    }


@pytest.mark.parametrize("recheck", [False, True])
def test_a_borrowed_figure_is_refused_before_any_recheck(recheck):
    """The checks refuse it on their own: nothing depends on the re-check, or on it being on."""
    corrected, provider, _ = run(
        "The flask keeps drinks hot for up to 6 hours.", "6 hours", "24 hours", recheck=recheck
    )
    attempt = corrected.correction_attempt
    assert corrected.correction is None and attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    assert [i.code for i in attempt.issues] == [Issue.UNSUPPORTED_ADDITION]
    assert attempt.recheck_verdict is None and len(provider.calls) == 1  # no re-check was asked
    assert corrected.verdict is Verdict.CONTRADICTED and corrected.requires_human_review


def test_a_grounded_correction_is_proposed_after_a_supported_recheck():
    sentence = "The flask keeps drinks hot for up to 6 hours."
    case_result = contradicted_result(flask_case(sentence))[0]
    corrected, provider, _ = run(sentence, "6 hours", "12 hours", supported_by(case_result))
    attempt = corrected.correction_attempt
    assert attempt.status is CorrectionStatus.PROPOSED
    assert attempt.recheck_verdict is Verdict.SUPPORTED
    assert corrected.correction.replacement_text == "12 hours"
    assert "hot for up to 12 hours" in provider.calls[1].user  # the corrected claim was re-checked


def test_the_recheck_still_refuses_an_untouched_unsupported_part():
    """Existing re-check behaviour, now with the Phase 4 guard: a narrow edit passes the checks, but
    the corrected claim still asserts a part no cited passage has, so a SUPPORTED re-check reply is
    downgraded and the proposal is refused."""
    sentence = "The flask keeps drinks hot for up to 6 hours and includes a lifetime warranty."
    case_result = contradicted_result(flask_case(sentence))[0]
    corrected, _, _ = run(sentence, "6 hours", "12 hours", supported_by(case_result))
    attempt = corrected.correction_attempt
    assert corrected.correction is None and attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    assert [i.code for i in attempt.issues] == [Issue.RECHECK_NOT_SUPPORTED]
    assert attempt.recheck_verdict is Verdict.NOT_ENOUGH_EVIDENCE


def test_the_guard_reason_behind_that_recheck_is_the_compound_rule():
    from inkloom_verify.citation_guard import support_problems

    claim = "The flask keeps drinks hot for up to 12 hours and includes a lifetime warranty."
    assert GuardRejectionReason.UNSUPPORTED_COMPONENT in support_problems(claim, FLASK, [SHEET])
