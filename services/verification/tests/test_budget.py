"""The per-request model-call budget (providers/budget.py): once a limit is reached, further calls
are refused with LIMIT_EXCEEDED, and a refused call never becomes a verdict."""

import pytest
from pydantic import ValidationError

from e2e_support import CONTRADICTED_CLAIM, SUPPORTED_CLAIM, RoutedProvider, careful_model, request
from inkloom_verify.pipeline import PipelineConfig, verify_request
from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest
from inkloom_verify.providers.budget import (
    BudgetedProvider,
    BudgetExceededError,
    CallBudget,
    estimate_tokens,
)
from inkloom_verify.schemas import CorrectionStatus, ErrorCode, ReportStatus, Verdict


def call(user: str = "x" * 400, max_output_tokens: int = 500) -> JsonCompletionRequest:
    return JsonCompletionRequest(
        system="s" * 400,
        user=user,
        schema_name="claim_verification",
        json_schema={"type": "object"},
        max_output_tokens=max_output_tokens,
    )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- The wrapper ---------------------------------------------------------------------------------


def test_calls_beyond_the_limit_are_refused_and_never_reach_the_provider():
    provider = RoutedProvider(lambda r: {"ok": True})
    budgeted = BudgetedProvider(provider, CallBudget(max_calls=2))
    budgeted.complete_json(call())
    budgeted.complete_json(call())
    with pytest.raises(BudgetExceededError) as refused:
        budgeted.complete_json(call())
    assert refused.value.code is ErrorCode.LIMIT_EXCEEDED and not refused.value.retryable
    assert len(provider.calls) == 2


def test_token_estimate_errs_high_and_is_enforced_before_the_call():
    assert estimate_tokens(call()) == 800 // 4 + 500
    provider = RoutedProvider(lambda r: {"ok": True})
    budgeted = BudgetedProvider(provider, CallBudget(max_estimated_tokens=1_000))
    budgeted.complete_json(call())  # 700 estimated
    with pytest.raises(BudgetExceededError, match="estimated tokens"):
        budgeted.complete_json(call())  # 1400 would exceed 1000
    assert len(provider.calls) == 1 and budgeted.estimated_tokens == 700


def test_deadline_is_enforced_with_an_injected_clock():
    clock = Clock()
    provider = RoutedProvider(lambda r: {"ok": True})
    budgeted = BudgetedProvider(provider, CallBudget(deadline_seconds=10), clock=clock)
    budgeted.complete_json(call())
    clock.now = 10.5
    with pytest.raises(BudgetExceededError, match="deadline"):
        budgeted.complete_json(call())
    assert len(provider.calls) == 1 and budgeted.usage()["seconds"] == 10.5


def test_provider_side_retries_count_against_the_budget():
    class Retrying(RoutedProvider):
        def complete_json(self, request):
            self.calls.append(request)
            return JsonCompletion(data={"ok": True}, model=self.model, attempts=3)

    budgeted = BudgetedProvider(Retrying(lambda r: None), CallBudget(max_calls=4))
    budgeted.complete_json(call())
    assert budgeted.calls == 3 and budgeted.estimated_tokens == 3 * 700
    budgeted.complete_json(call())  # 3 < 4, so allowed; now 6
    with pytest.raises(BudgetExceededError):
        budgeted.complete_json(call())


@pytest.mark.parametrize(
    "bad",
    [
        {"max_calls": 0},
        {"max_calls": 10_000},
        {"max_estimated_tokens": 10},
        {"deadline_seconds": 0},
        {"deadline_seconds": 86_400},
        {"unknown": 1},
    ],
)
def test_budget_settings_are_bounded(bad):
    with pytest.raises(ValidationError):
        CallBudget(**bad)


# --- Through the pipeline: a refused call is never a verdict --------------------------------------


def test_exhausted_budget_turns_remaining_claims_into_errors_not_verdicts():
    provider = RoutedProvider(careful_model)
    report = verify_request(request(), provider, PipelineConfig(budget=CallBudget(max_calls=1)))
    assert len(provider.calls) == 1  # extraction only
    assert report.results and all(r.verdict is Verdict.ERROR for r in report.results)
    assert {r.error.code for r in report.results} == {ErrorCode.LIMIT_EXCEEDED}
    assert report.status is not ReportStatus.COMPLETED and report.score.requires_human_review


def test_token_limit_during_extraction_fails_the_report():
    provider = RoutedProvider(careful_model)
    report = verify_request(
        request(), provider, PipelineConfig(budget=CallBudget(max_estimated_tokens=1_000))
    )
    assert provider.calls == []  # extraction's 4000-token output allowance alone exceeds the limit
    assert report.status is ReportStatus.FAILED and report.results == []
    assert [e.code for e in report.errors] == [ErrorCode.LIMIT_EXCEEDED]


def test_budget_stop_during_correction_keeps_the_verdict_and_requests_review():
    provider = RoutedProvider(careful_model)
    report = verify_request(
        request(CONTRADICTED_CLAIM), provider, PipelineConfig(budget=CallBudget(max_calls=2))
    )
    [result] = report.results
    assert result.verdict is Verdict.CONTRADICTED and result.correction is None
    assert result.correction_attempt.status is CorrectionStatus.FAILED
    assert result.requires_human_review


@pytest.mark.parametrize("limit", range(1, 9))
def test_no_call_limit_ever_creates_or_changes_a_verdict(limit):
    unlimited = {
        r.claim.text: r.verdict
        for r in verify_request(request(), RoutedProvider(careful_model)).results
    }
    provider = RoutedProvider(careful_model)
    report = verify_request(request(), provider, PipelineConfig(budget=CallBudget(max_calls=limit)))
    assert len(provider.calls) <= limit
    for result in report.results:
        if result.verdict is Verdict.ERROR:
            assert result.error.code in (ErrorCode.LIMIT_EXCEEDED, ErrorCode.PROVIDER_TIMEOUT)
        else:
            assert result.verdict is unlimited[result.claim.text]  # never upgraded by a budget stop
    supported = [r for r in report.results if r.verdict is Verdict.SUPPORTED]
    assert all(r.claim.text == SUPPORTED_CLAIM for r in supported)
