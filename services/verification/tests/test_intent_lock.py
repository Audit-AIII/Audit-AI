"""Intent-lock (intent_lock.py; DESIGN.md §22 "protected spans cannot change in a suggestion").

Deterministic enforcement, never a prompt instruction: the corrector and the softener refuse a
proposal that removes locked text, and the backend can apply the same check to anything it stores.
Locks are exact, case-sensitive phrases, as in the frontend (lib/additions/locks.ts)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inkloom_verify.correction import ClaimCorrector, CorrectionConfig
from inkloom_verify.evaluation.corrections import contradicted_result, load_cases
from inkloom_verify.intent_lock import (
    MAX_LOCK_CHARS,
    MAX_LOCKS,
    IntentLockError,
    check_replacement,
    intent_lock_violations,
    validate_locks,
)
from inkloom_verify.providers.fake import ScriptedProvider
from inkloom_verify.schemas import (
    Claim,
    ClaimResult,
    CorrectionIssueCode,
    CorrectionStatus,
    InputContent,
    SourceSpan,
    Verdict,
)
from inkloom_verify.softening import ClaimSoftener
from inkloom_verify.verification import ClaimVerifier

CASES = {
    c.case_id: c
    for c in load_cases(
        Path(__file__).resolve().parents[1] / "eval" / "data" / "corrections_v1.jsonl"
    )
}


# --- The validator --------------------------------------------------------------------------------


def test_removing_a_locked_phrase_is_a_violation_and_keeping_it_is_not():
    original = "Lumen Pods cost ₹2,499 and ship on 2 April."
    assert (
        intent_lock_violations(original, "Lumen Pods ship on 2 April.", ["₹2,499"])[0].phrase
        == "₹2,499"
    )
    assert (
        intent_lock_violations(
            original, "Lumen Pods now cost ₹2,499 and ship on 2 April.", ["₹2,499"]
        )
        == []
    )


def test_locks_are_exact_and_case_sensitive_like_the_frontend():
    assert intent_lock_violations(
        "Buy Lumen Pods", "Buy lumen pods", ["Lumen Pods"]
    )  # case changed: violation
    assert intent_lock_violations("Buy Lumen Pods", "Buy Lumen Pods!", ["Lumen Pods"]) == []


def test_removing_one_of_several_occurrences_is_caught():
    [v] = intent_lock_violations(
        "₹2,499 today, ₹2,499 tomorrow", "₹2,499 today, cheaper tomorrow", ["₹2,499"]
    )
    assert (v.occurrences_before, v.occurrences_after) == (2, 1)


def test_a_lock_absent_from_the_original_constrains_nothing():
    assert intent_lock_violations("Plain text.", "Other text.", ["₹2,499"]) == []


def test_a_lock_straddling_the_edit_boundary_is_caught():
    text = "Order the Lumen Pods Max today."
    start = text.index("Max")
    assert check_replacement(text, start, start + 3, "Pro", ["Lumen Pods Max"])  # only "Max" edited
    with pytest.raises(ValueError):
        check_replacement(text, 5, 999, "x", ["Lumen"])


@pytest.mark.parametrize(
    "locks",
    [
        "₹2,499",
        [""],
        ["   "],
        [42],
        ["x" * (MAX_LOCK_CHARS + 1)],
        [f"l{i}" for i in range(MAX_LOCKS + 1)],
    ],
)
def test_malformed_locks_are_refused_never_silently_dropped(locks):
    with pytest.raises(IntentLockError):
        validate_locks(locks)


def test_duplicate_locks_are_kept_once_in_order():
    assert validate_locks(["₹2,499", "2 April", "₹2,499"]) == ["₹2,499", "2 April"]


# --- The corrector respects locks -----------------------------------------------------------------


def _correct(locks):
    case = CASES[
        "corr-v1-020"
    ]  # "Lumen Pods offer up to 24 hours of playback per charge." -> 24 is 12
    result, content = contradicted_result(case)
    quote = result.citations[0].quote
    provider = ScriptedProvider(
        {
            "status": "corrected",
            "original_text": "24",
            "replacement_text": "12",
            "citations": ["C1"],
            "reason": "Per C1.",
        },
        lambda request: {
            "verdict": "SUPPORTED",
            "citations": [{"passage": "P1", "quote": quote}],
            "rationale": "P1.",
        },
    )
    corrector = ClaimCorrector(
        provider, ClaimVerifier(provider, case.references), CorrectionConfig()
    )
    return corrector.correct(result, content, locked_phrases=locks), provider


def test_a_correction_that_would_change_locked_text_is_refused_and_the_verdict_stands():
    corrected, provider = _correct(["24 hours"])
    assert corrected.verdict is Verdict.CONTRADICTED and corrected.correction is None
    assert corrected.correction_attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    assert [i.code for i in corrected.correction_attempt.issues] == [
        CorrectionIssueCode.INTENT_LOCK
    ]
    assert len(provider.calls) == 1  # refused before the re-check: no extra model call
    ClaimResult.model_validate(corrected.model_dump())


def test_a_lock_the_correction_does_not_touch_does_not_block_it():
    corrected, _ = _correct(["Lumen Pods"])
    assert corrected.correction is not None and corrected.correction.replacement_text == "12"


def test_no_locks_behaves_exactly_as_before():
    assert _correct([])[0].correction is not None


# --- The softener respects locks ------------------------------------------------------------------


def test_a_softening_that_would_remove_locked_text_is_refused():
    text = "The Kora X2 is India's number one smartphone at ₹24,999."
    claim = Claim(claim_id="clm_0001", text=text, source_span=SourceSpan(start=0, end=len(text)))
    result, content = (
        ClaimResult(claim=claim, verdict=Verdict.NOT_ENOUGH_EVIDENCE),
        InputContent(text=text),
    )
    reply = {
        "status": "softened",
        "original_text": "India's number one smartphone",
        "replacement_text": "a smartphone sold in India",
        "citations": [],
        "reason": "No ranking evidence.",
    }

    locked = ClaimSoftener(ScriptedProvider(dict(reply)))
    assert locked.soften(result, content, locked_phrases=["number one"]) is None
    assert locked.last_issues == ["intent_lock"]

    free = ClaimSoftener(ScriptedProvider(dict(reply)))
    assert (
        free.soften(result, content, locked_phrases=["₹24,999"]) is not None
    )  # the price lock is untouched


def test_malformed_locks_stop_the_suggestion_before_any_model_call():
    text = "Kora is the best phone."
    claim = Claim(claim_id="clm_0001", text=text, source_span=SourceSpan(start=0, end=len(text)))
    provider = ScriptedProvider()
    with pytest.raises(IntentLockError):
        ClaimSoftener(provider).soften(
            ClaimResult(claim=claim, verdict=Verdict.NOT_ENOUGH_EVIDENCE),
            InputContent(text=text),
            locked_phrases=[""],
        )
    assert provider.calls == []


# --- Through the engine pipeline (VerificationRequest.locked_phrases) ----------------------------


def test_the_pipeline_passes_locks_to_the_corrector():
    from e2e_support import CONTRADICTED_CLAIM, RoutedProvider, careful_model, request
    from inkloom_verify.pipeline import verify_request
    from inkloom_verify.schemas import VerificationRequest

    plain = verify_request(request(CONTRADICTED_CLAIM), RoutedProvider(careful_model))
    assert plain.results[0].correction is not None  # "The Lumen Pods price is €99." -> €129
    locked_request = VerificationRequest.model_validate(
        request(CONTRADICTED_CLAIM).model_dump() | {"locked_phrases": ["€99"]}
    )
    locked = verify_request(locked_request, RoutedProvider(careful_model))
    [result] = locked.results
    assert result.verdict is Verdict.CONTRADICTED and result.correction is None
    assert [i.code for i in result.correction_attempt.issues] == [CorrectionIssueCode.INTENT_LOCK]


def test_blank_locked_phrases_are_refused_by_the_request_contract():
    from e2e_support import request
    from inkloom_verify.schemas import VerificationRequest

    with pytest.raises(ValueError):
        VerificationRequest.model_validate(request().model_dump() | {"locked_phrases": ["   "]})
