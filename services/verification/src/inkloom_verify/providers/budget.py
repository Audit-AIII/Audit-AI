"""A per-request budget on model calls: how many, how many (estimated) tokens, and for how long.

The engine makes one call per extraction batch and per claim, plus up to four per CONTRADICTED
claim (correction, its repair, the re-check and its repair) and up to two per NOT_ENOUGH_EVIDENCE
claim when a safer wording is requested (softening and its repair; softening.py), so one large
request could otherwise make hundreds of calls. ``BudgetedProvider`` wraps the request's provider and refuses
further calls once any limit is reached. The refusal is a ProviderError with code LIMIT_EXCEEDED
and is not retryable, so every stage turns it into an ERROR result, a FAILED report or a FAILED
correction, never a verdict.

Tokens are estimated, not counted: prompt characters / 4 plus the call's ``max_output_tokens``
(the most the provider may return). The estimate errs high, so the limit is conservative.
Provider-side retries happen inside one call; their attempts are added after the call returns.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest, LLMProvider, ProviderError
from inkloom_verify.schemas import ErrorCode

CHARS_PER_TOKEN = 4


class CallBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(default=200, ge=1, le=5_000)
    max_estimated_tokens: int = Field(default=1_000_000, ge=1_000, le=50_000_000)
    deadline_seconds: float = Field(default=300.0, gt=0, le=3_600)


class BudgetExceededError(ProviderError):
    """The request used up its model-call budget. Not retryable within this request."""

    code = ErrorCode.LIMIT_EXCEEDED


def estimate_tokens(request: JsonCompletionRequest) -> int:
    return (len(request.system) + len(request.user)) // CHARS_PER_TOKEN + request.max_output_tokens


class BudgetedProvider:
    """Wraps one request's provider; refuses calls beyond the budget."""

    def __init__(self, provider: LLMProvider, budget: CallBudget, clock: Callable[[], float] = time.monotonic) -> None:
        self.provider = provider
        self.name = provider.name
        self.budget = budget
        self._clock = clock
        self._started = clock()
        self.calls = 0
        self.estimated_tokens = 0

    def sampling(self) -> dict[str, Any]:
        return self.provider.sampling()

    def usage(self) -> dict[str, Any]:
        return {"calls": self.calls, "estimated_tokens": self.estimated_tokens,
                "seconds": round(self._clock() - self._started, 3)}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        estimate = estimate_tokens(request)
        if self.calls >= self.budget.max_calls:
            raise BudgetExceededError(f"Request stopped: it reached its limit of {self.budget.max_calls} model calls.")
        if self.estimated_tokens + estimate > self.budget.max_estimated_tokens:
            raise BudgetExceededError(
                f"Request stopped: it would exceed its limit of {self.budget.max_estimated_tokens} estimated tokens."
            )
        if self._clock() - self._started > self.budget.deadline_seconds:
            raise BudgetExceededError(f"Request stopped: it ran past its {self.budget.deadline_seconds:g}s deadline.")
        self.calls += 1
        self.estimated_tokens += estimate
        completion = self.provider.complete_json(request)
        extra = max(completion.attempts - 1, 0)  # provider-side retries spent more than one call
        self.calls += extra
        self.estimated_tokens += extra * estimate
        return completion
