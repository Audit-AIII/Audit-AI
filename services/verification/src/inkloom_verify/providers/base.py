"""The provider-neutral interface every LLM stage calls, and the errors it may raise.

Stages ask for one JSON object that matches a schema; the provider returns it parsed but
otherwise untrusted. Validating it against a Pydantic model is the stage's job.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from inkloom_verify.schemas import ErrorCode, PipelineStage, ProcessingError


class ProviderError(Exception):
    """A provider call failed. ``str(error)`` is safe to show and log: no secrets, no content."""

    code = ErrorCode.PROVIDER_ERROR
    retryable = False

    def to_processing_error(self, stage: PipelineStage, claim_id: str | None = None) -> ProcessingError:
        retry_after = getattr(self, "retry_after", None)
        return ProcessingError(
            code=self.code, stage=stage, message=str(self)[:500], retryable=self.retryable, claim_id=claim_id,
            retry_after_seconds=min(math.ceil(retry_after), 3_600) if retry_after is not None and retry_after >= 0 else None,
        )


class ProviderNotConfiguredError(ProviderError):
    """Credentials or models are missing or invalid. The message names the variables, never their values."""

    code = ErrorCode.PROVIDER_NOT_CONFIGURED


class ProviderAuthError(ProviderError):
    """The provider rejected the credentials or refused the request (401/403)."""


class ProviderQuotaError(ProviderError):
    """The account has no credit left (402). Retrying will not help."""

    code = ErrorCode.PROVIDER_QUOTA_EXCEEDED


class ProviderRequestError(ProviderError):
    """The provider rejected this request for this model (400/404/413/422). Another model may accept it."""


class ProviderTimeoutError(ProviderError):
    code = ErrorCode.PROVIDER_TIMEOUT
    retryable = True


class ProviderRateLimitError(ProviderError):
    code = ErrorCode.PROVIDER_RATE_LIMITED
    retryable = True

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    """Network failure, 5xx, or a failure reported inside a 200 response."""

    retryable = True


class MalformedOutputError(ProviderError):
    """The model's reply is not one JSON object (empty, truncated, or not JSON)."""

    code = ErrorCode.MALFORMED_MODEL_OUTPUT
    retryable = True


# Errors about the account or configuration: no other model and no retry can fix them.
ACCOUNT_ERRORS = (ProviderNotConfiguredError, ProviderAuthError, ProviderQuotaError)


class JsonCompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    system: str = Field(min_length=1)
    user: str = Field(min_length=1)
    schema_name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    json_schema: dict[str, Any]
    max_output_tokens: int = Field(default=4_000, ge=1, le=32_000)


class JsonCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data: dict[str, Any]
    model: str  # the model that actually answered
    attempts: int = Field(ge=1)


class LLMProvider(Protocol):
    """One configured LLM provider."""

    name: str

    def sampling(self) -> dict[str, Any]:
        """The sampling settings sent with each call, for provenance (e.g. temperature, seed)."""
        ...

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        """One JSON object answering ``request``, or a ProviderError."""
        ...


_FENCE = re.compile(r"^\s*```(?:json)?\s*\n(.*)\n\s*```\s*$", re.DOTALL)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        # Python's json would silently keep the last value: {"verdict": "X", "verdict": "SUPPORTED"}.
        raise ValueError("duplicate key")
    return dict(pairs)


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")  # NaN, Infinity, -Infinity


def parse_json_object(text: str) -> dict[str, Any]:
    """A model reply as one strict JSON object, or MalformedOutputError.

    Strict means standard JSON only: no duplicate keys (Python's json silently keeps the last
    one), no NaN or Infinity, and a top-level object. A reply asked to be JSON is never trusted to
    be JSON. The single tolerated wrapper is one Markdown code fence around the whole reply.
    Messages are fixed: the reply is never echoed.
    """
    fenced = _FENCE.match(text)
    try:
        data = json.loads(fenced.group(1) if fenced else text, object_pairs_hook=_no_duplicate_keys,
                          parse_constant=_no_constant)
    except (ValueError, RecursionError):  # RecursionError: pathologically nested JSON
        raise MalformedOutputError("reply is not valid JSON") from None
    if not isinstance(data, dict):
        raise MalformedOutputError("reply is JSON but not an object")
    return data
