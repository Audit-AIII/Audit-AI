"""OpenRouter adapter (OpenAI-compatible chat completions, https://openrouter.ai/docs).

Configuration comes only from the environment; nothing is hard-coded. Models are tried in the
configured order: a model is retried on transient failures (timeout, 429, 5xx, malformed
output), then the next model is tried. Account problems (missing or rejected credentials, no
credit) stop immediately because no other model can fix them.

Structured output: in "json_schema" mode the request carries ``require_parameters: true``, so
OpenRouter answers 404 "No endpoints found that can handle the requested parameters" for a model
with no endpoint that supports strict JSON Schema (many ``:free`` models). That model is then
tried once more, immediately, in "json_object" mode (the documented fallback) instead of being
skipped; ``data_collection`` and ``require_parameters`` stay as configured, and the reply is
still parsed strictly and validated by the calling stage. Any other 404 (an unknown model id)
moves to the next model as before.

Determinism: requests use the configured temperature (default 0) and seed. Providers treat these
as best effort, so identical requests can still return different outputs.
"""

from __future__ import annotations

import logging
import os
import random
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator

from inkloom_verify.providers.base import (
    ACCOUNT_ERRORS,
    JsonCompletion,
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderAuthError,
    ProviderError,
    ProviderNotConfiguredError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    parse_json_object,
)
from inkloom_verify.security import install_redaction, register_secret

logger = logging.getLogger(__name__)

# OpenRouter's 404 messages when routing leaves no endpoint for a model. Matched to classify the
# 404 only; the provider's text is never echoed (see _error). Two different causes:
#   "No endpoints found that can handle the requested parameters."  -> require_parameters
#   "No endpoints found matching your data policy (...)"            -> data_collection=deny (or the
#      account's privacy settings) excludes every endpoint, e.g. a free model whose only provider
#      may train on prompts. Switching structured-output mode cannot help that.
_NO_ENDPOINTS_FOR_PARAMETERS = re.compile(
    r"no endpoints found that can handle the requested parameters", re.IGNORECASE
)
_NO_ENDPOINTS_FOR_DATA_POLICY = re.compile(
    r"no endpoints found matching your data policy", re.IGNORECASE
)


class UnsupportedParametersError(ProviderRequestError):
    """404: no endpoint of this model supports the requested parameters (require_parameters)."""


# OpenRouter's 429 when the account's daily allowance for :free models is used up. Every :free model
# shares it, so it is a quota (not a transient rate limit): retrying or trying another :free model
# cannot succeed until it resets. Matched to classify only; the text is never echoed.
_FREE_MODEL_QUOTA = re.compile(r"free-models-per-day", re.IGNORECASE)


class FreeModelQuotaError(ProviderQuotaError):
    """429 free-models-per-day: the daily quota for :free models is exhausted. Never retried; the
    remaining :free models are skipped; a paid model later in the list is still tried."""


class DataPolicyError(ProviderRequestError):
    """404: every endpoint of this model is excluded by the data policy (data_collection=deny or the
    account's OpenRouter privacy settings). Not retried and no fallback: the next model is tried."""


API_KEY_VAR = "OPENROUTER_API_KEY"
MODELS_VAR = "INKLOOM_LLM_MODELS"
MAX_MODELS = 5
# An OpenRouter model id: "<provider>/<model>" with an optional ":<variant>" (":free", ":nitro").
# One slash, so a URL ("https://openrouter.ai/x/y") is refused instead of being sent as a model id.
MODEL_ID = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+(?::[A-Za-z0-9._-]+)?")
MODELS_FORMAT = (
    f"{MODELS_VAR} must be a comma-separated list of 1 to {MAX_MODELS} OpenRouter model ids, tried in "
    "order, with no quotes or brackets, e.g. nvidia/nemotron-3.5-super-vl:free or "
    "nvidia/nemotron-3.5-super-vl:free,meta-llama/llama-3.3-70b-instruct:free"
)
_OPTIONAL_VARS = {
    "base_url": "OPENROUTER_BASE_URL",
    "timeout_seconds": "INKLOOM_LLM_TIMEOUT_SECONDS",
    "max_retries": "INKLOOM_LLM_MAX_RETRIES",
    "min_interval_seconds": "INKLOOM_LLM_MIN_INTERVAL_SECONDS",
    "seed": "INKLOOM_LLM_SEED",
    "structured_output": "INKLOOM_LLM_STRUCTURED_OUTPUT",
    "data_collection": "INKLOOM_LLM_DATA_COLLECTION",
}
_MAX_RETRY_AFTER_SECONDS = 20.0
MAX_RESPONSE_BYTES = 2_000_000  # far above any reply max_tokens allows; guards memory


class OpenRouterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    models: list[str] = Field(min_length=1, max_length=MAX_MODELS)
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    backoff_seconds: float = Field(default=1.0, ge=0, le=30)
    # Minimum pause between two requests, to stay under a provider's rate limit in a long run.
    # 0 (the default) sends requests as fast as the caller asks.
    min_interval_seconds: float = Field(default=0.0, ge=0, le=30)
    temperature: float = Field(default=0.0, ge=0, le=2)
    seed: int | None = 0
    # "json_schema" asks for schema-constrained output and only routes to endpoints that support
    # it; "json_object" is the fallback for models without structured-output support.
    structured_output: Literal["json_schema", "json_object"] = "json_schema"
    # "deny" routes only to providers that do not collect prompt data.
    data_collection: Literal["deny", "allow"] = "deny"

    @field_validator("api_key")
    @classmethod
    def _key_present(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("models")
    @classmethod
    def _model_ids(cls, value: list[str]) -> list[str]:
        for model in value:
            if len(model) > 128 or not MODEL_ID.fullmatch(model):
                raise ValueError(
                    "each model must be an OpenRouter model id such as provider/model-name"
                )
        return value

    @field_validator("base_url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("must be an https:// URL so the API key is never sent in clear text")
        return value.rstrip("/")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenRouterSettings:
        """Reads the settings, or raises ProviderNotConfiguredError naming what is missing or invalid."""
        env = os.environ if env is None else env
        missing = [name for name in (API_KEY_VAR, MODELS_VAR) if not env.get(name, "").strip()]
        if missing:
            raise ProviderNotConfiguredError(
                f"LLM provider not configured: set {' and '.join(missing)}. "
                f"{MODELS_FORMAT}. "
                "AI checks are unavailable until then."
            )
        values: dict[str, Any] = {
            "api_key": env[API_KEY_VAR].strip(),
            "models": [m.strip() for m in env[MODELS_VAR].split(",") if m.strip()],
        }
        for field, name in _OPTIONAL_VARS.items():
            if env.get(name, "").strip():
                values[field] = env[name].strip()
        if str(values.get("seed", "")).lower() == "none":  # INKLOOM_LLM_SEED=none sends no seed
            values["seed"] = None
        try:
            return cls(**values)
        except ValidationError as error:
            names = {"api_key": API_KEY_VAR, "models": MODELS_VAR, **_OPTIONAL_VARS}
            fields = sorted({names.get(str(e["loc"][0]), str(e["loc"][0])) for e in error.errors()})
            # Field names only: validation messages could echo the values, including the key.
            message = f"LLM provider misconfigured: invalid {', '.join(fields)}."
            if MODELS_VAR in fields:
                message += " " + MODELS_FORMAT + "." + models_hint(env[MODELS_VAR])
            raise ProviderNotConfiguredError(message) from None


def models_hint(raw: str) -> str:
    """What looks wrong with an INKLOOM_LLM_MODELS value, described without repeating it (someone
    may have pasted a key into the wrong variable)."""
    value = raw.strip()
    found = []
    if any(q in value for q in "\"'`"):
        found.append(
            'it contains quote characters (cmd\'s set VAR="..." keeps the quotes; write set VAR=value)'
        )
    if any(b in value for b in "[]{}"):
        found.append(
            "it contains brackets (JSON is not accepted; use a plain comma-separated list)"
        )
    if ";" in value or any(
        " " in part.strip() or "\t" in part.strip() for part in value.split(",")
    ):
        found.append("models are separated by something other than commas")
    if "=" in value:
        found.append("it contains '=' (a name=model mapping is not accepted)")
    if "://" in value:
        found.append("it contains a URL (use the model id only, e.g. provider/model)")
    count = len([m for m in value.split(",") if m.strip()])
    if count > MAX_MODELS:
        found.append(f"it lists {count} models (at most {MAX_MODELS})")
    return (" Detected: " + "; ".join(found) + ".") if found else ""


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        settings: OpenRouterSettings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self._jitter = jitter
        # Redirects are never followed, so the Authorization header cannot be sent to another host.
        self._client = client or httpx.Client(
            timeout=settings.timeout_seconds, follow_redirects=False
        )
        self._sleep = sleep
        self._last_request_at: float | None = None
        self._secret = settings.api_key.get_secret_value()
        register_secret(self._secret)
        install_redaction(logger)
        # Refusals that cannot change during one run (an evaluation, a request), remembered so that
        # later calls skip them without a network request instead of failing the same way again.
        self._refused_models: dict[str, ProviderError] = {}  # model -> DataPolicyError
        self._free_quota_error: FreeModelQuotaError | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> OpenRouterProvider:
        return cls(OpenRouterSettings.from_env(env))

    def sampling(self) -> dict[str, Any]:
        return {
            "temperature": self.settings.temperature,
            "seed": self.settings.seed,
            "structured_output": self.settings.structured_output,
            "data_collection": self.settings.data_collection,
        }

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        attempts = 0
        last: ProviderError | None = None
        for model in self.settings.models:
            if model in self._refused_models:
                last = self._refused_models[model]
                continue
            if self._free_quota_error is not None and model.endswith(":free"):
                last = self._free_quota_error
                continue
            mode = self.settings.structured_output
            retry = 0
            while retry <= self.settings.max_retries:
                attempts += 1
                try:
                    data, answered_by = self._call(model, request, mode)
                    return JsonCompletion(data=data, model=answered_by, attempts=attempts)
                except FreeModelQuotaError as error:
                    last = self._free_quota_error = error
                    logger.warning(
                        "openrouter model=%s: daily free-model quota exhausted; skipping :free models",
                        model,
                    )
                    break
                except ACCOUNT_ERRORS:
                    raise
                except DataPolicyError as error:
                    last = self._refused_models[model] = error
                    logger.warning(
                        "openrouter model=%s rejected by the data policy; skipped for this run",
                        model,
                    )
                    break
                except UnsupportedParametersError as error:
                    last = error
                    if mode == "json_schema":
                        # Same model, schema-less JSON mode; does not use up a retry or wait.
                        logger.warning(
                            "openrouter model=%s has no endpoint for json_schema; retrying with json_object",
                            model,
                        )
                        mode = "json_object"
                        continue
                    logger.warning("openrouter model=%s rejected the request: %s", model, error)
                    break
                except ProviderRequestError as error:
                    last = error
                    logger.warning("openrouter model=%s rejected the request: %s", model, error)
                    break  # retrying the same request on the same model will not help
                except ProviderError as error:
                    last = error
                    logger.warning(
                        "openrouter model=%s attempt=%d failed: %s", model, retry + 1, error
                    )
                    if retry < self.settings.max_retries:
                        self._sleep(self._delay(error, retry))
                retry += 1
        assert last is not None
        raise last

    def _delay(self, error: ProviderError, retry: int) -> float:
        if isinstance(error, ProviderRateLimitError) and error.retry_after is not None:
            return min(error.retry_after, _MAX_RETRY_AFTER_SECONDS)
        # Exponential steps with "equal jitter" (a random factor in [0.5, 1]) so concurrent requests
        # don't retry in lockstep; never longer than the Retry-After cap.
        step = self.settings.backoff_seconds * (2**retry)
        return min(step * (0.5 + self._jitter() / 2), _MAX_RETRY_AFTER_SECONDS)

    def _body(
        self, model: str, request: JsonCompletionRequest, mode: str | None = None
    ) -> dict[str, Any]:
        if (mode or self.settings.structured_output) == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.json_schema,
                },
            }
        else:
            response_format = {"type": "json_object"}
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": self.settings.temperature,
            "max_tokens": request.max_output_tokens,
            "response_format": response_format,
            "provider": {
                "data_collection": self.settings.data_collection,
                "require_parameters": True,
            },
        }
        if self.settings.seed is not None:
            body["seed"] = self.settings.seed
        return body

    def _call(
        self, model: str, request: JsonCompletionRequest, mode: str | None = None
    ) -> tuple[dict[str, Any], str]:
        if self.settings.min_interval_seconds and self._last_request_at is not None:
            wait = self.settings.min_interval_seconds - (time.monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        started = self._last_request_at = time.monotonic()
        try:
            response = self._client.post(
                f"{self.settings.base_url}/chat/completions",
                json=self._body(model, request, mode),
                headers={"Authorization": f"Bearer {self._secret}"},
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise ProviderTimeoutError(
                f"{model} did not answer within {self.settings.timeout_seconds:g}s"
            ) from None
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(
                f"could not reach OpenRouter ({type(error).__name__})"
            ) from None
        logger.info(
            "openrouter model=%s status=%d seconds=%.2f",
            model,
            response.status_code,
            time.monotonic() - started,
        )

        payload = self._json_body(response, model)
        if response.status_code != 200 or "error" in payload:
            raise self._error(response, payload, model)
        return self._content(payload, model), str(payload.get("model") or model)

    def _json_body(self, response: httpx.Response, model: str) -> dict[str, Any]:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ProviderUnavailableError(
                f"{model}: OpenRouter response exceeded {MAX_RESPONSE_BYTES} bytes"
            )
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            payload = None
        if isinstance(payload, dict):
            return payload
        if response.status_code == 200:
            raise ProviderUnavailableError(
                f"{model}: OpenRouter returned a response that is not a JSON object"
            )
        return {}

    def _error(
        self, response: httpx.Response, payload: dict[str, Any], model: str
    ) -> ProviderError:
        """A ProviderError with a fixed, safe message.

        The provider's own error text is deliberately dropped, not just redacted: it can echo
        submitted content (moderation errors do), and errors are shown to clients and logged.
        """
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        status = response.status_code if response.status_code != 200 else error.get("code", 0)
        status = status if isinstance(status, int) else 0
        message = f"{model}: OpenRouter returned error {status}"
        if status == 401:
            return ProviderAuthError(f"OpenRouter rejected the API key ({API_KEY_VAR}).")
        if status == 402:
            return ProviderQuotaError("OpenRouter account has insufficient credit.")
        if status == 403:
            return ProviderAuthError(message)
        if status == 408:
            return ProviderTimeoutError(message)
        if status == 429 and _FREE_MODEL_QUOTA.search(
            error.get("message") if isinstance(error.get("message"), str) else ""
        ):
            return FreeModelQuotaError(
                "OpenRouter's daily quota for :free models is exhausted (429 free-models-per-day). No :free model "
                "can answer until it resets; use a paid model with a compliant endpoint, or wait."
            )
        if status == 429:
            return ProviderRateLimitError(message, _retry_after(response))
        provider_message = error.get("message") if isinstance(error.get("message"), str) else ""
        if status == 404 and _NO_ENDPOINTS_FOR_DATA_POLICY.search(provider_message):
            return DataPolicyError(
                f"{model}: no endpoint matches the data policy (404); with {_OPTIONAL_VARS['data_collection']}=deny a model "
                "whose providers may train on or log prompts cannot be used (see https://openrouter.ai/settings/privacy)"
            )
        if status == 404 and _NO_ENDPOINTS_FOR_PARAMETERS.search(provider_message):
            return UnsupportedParametersError(
                f"{model}: no endpoint supports the requested parameters (404)"
            )
        if status in (400, 404, 413, 422):
            return ProviderRequestError(message)
        return ProviderUnavailableError(message)

    def _content(self, payload: dict[str, Any], model: str) -> dict[str, Any]:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderUnavailableError(f"{model}: response has no choices")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "error":
            raise ProviderUnavailableError(f"{model}: generation failed after it started")
        if finish == "length":
            raise MalformedOutputError(f"{model}: reply was cut off at the output token limit")
        content = (choice.get("message") or {}).get("content")
        if not isinstance(content, str) or not content.strip():
            raise MalformedOutputError(f"{model}: reply is empty")
        try:
            return parse_json_object(content)  # strict: no duplicate keys, no NaN, an object
        except MalformedOutputError as error:
            raise MalformedOutputError(f"{model}: {error}") from None


def _retry_after(response: httpx.Response) -> float | None:
    try:
        value = float(response.headers.get("retry-after", ""))
    except ValueError:
        return None
    return value if value >= 0 else None
