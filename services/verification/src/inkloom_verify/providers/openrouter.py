"""OpenRouter adapter (OpenAI-compatible chat completions, https://openrouter.ai/docs).

Configuration comes only from the environment; nothing is hard-coded. Models are tried in the
configured order: a model is retried on transient failures (timeout, 429, 5xx, malformed
output), then the next model is tried. Account problems (missing or rejected credentials, no
credit) stop immediately because no other model can fix them.

Determinism: requests use the configured temperature (default 0) and seed. Providers treat these
as best effort, so identical requests can still return different outputs.
"""

from __future__ import annotations

import logging
import os
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
    parse_json_object,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from inkloom_verify.security import install_redaction, register_secret

logger = logging.getLogger(__name__)

API_KEY_VAR = "OPENROUTER_API_KEY"
MODELS_VAR = "INKLOOM_LLM_MODELS"
_OPTIONAL_VARS = {
    "base_url": "OPENROUTER_BASE_URL",
    "timeout_seconds": "INKLOOM_LLM_TIMEOUT_SECONDS",
    "max_retries": "INKLOOM_LLM_MAX_RETRIES",
    "seed": "INKLOOM_LLM_SEED",
    "structured_output": "INKLOOM_LLM_STRUCTURED_OUTPUT",
    "data_collection": "INKLOOM_LLM_DATA_COLLECTION",
}
_MAX_RETRY_AFTER_SECONDS = 20.0
MAX_RESPONSE_BYTES = 2_000_000  # far above any reply max_tokens allows; guards memory


class OpenRouterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    models: list[str] = Field(min_length=1, max_length=5)
    base_url: str = "https://openrouter.ai/api/v1"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    backoff_seconds: float = Field(default=1.0, ge=0, le=30)
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
            if not re.fullmatch(r"[A-Za-z0-9._:/-]{3,128}", model):
                raise ValueError("each model must be an OpenRouter model id such as provider/model-name")
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
                f"{MODELS_VAR} is a comma-separated list of OpenRouter model ids, tried in order. "
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
            raise ProviderNotConfiguredError(f"LLM provider misconfigured: invalid {', '.join(fields)}.") from None


class OpenRouterProvider:
    name = "openrouter"

    def __init__(
        self,
        settings: OpenRouterSettings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        # Redirects are never followed, so the Authorization header cannot be sent to another host.
        self._client = client or httpx.Client(timeout=settings.timeout_seconds, follow_redirects=False)
        self._sleep = sleep
        self._secret = settings.api_key.get_secret_value()
        register_secret(self._secret)
        install_redaction(logger)

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
            for retry in range(self.settings.max_retries + 1):
                attempts += 1
                try:
                    data, answered_by = self._call(model, request)
                    return JsonCompletion(data=data, model=answered_by, attempts=attempts)
                except ACCOUNT_ERRORS:
                    raise
                except ProviderRequestError as error:
                    last = error
                    logger.warning("openrouter model=%s rejected the request: %s", model, error)
                    break  # retrying the same request on the same model will not help
                except ProviderError as error:
                    last = error
                    logger.warning("openrouter model=%s attempt=%d failed: %s", model, retry + 1, error)
                    if retry < self.settings.max_retries:
                        self._sleep(self._delay(error, retry))
        assert last is not None
        raise last

    def _delay(self, error: ProviderError, retry: int) -> float:
        if isinstance(error, ProviderRateLimitError) and error.retry_after is not None:
            return min(error.retry_after, _MAX_RETRY_AFTER_SECONDS)
        return self.settings.backoff_seconds * (2**retry)

    def _body(self, model: str, request: JsonCompletionRequest) -> dict[str, Any]:
        if self.settings.structured_output == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "strict": True, "schema": request.json_schema},
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
            "provider": {"data_collection": self.settings.data_collection, "require_parameters": True},
        }
        if self.settings.seed is not None:
            body["seed"] = self.settings.seed
        return body

    def _call(self, model: str, request: JsonCompletionRequest) -> tuple[dict[str, Any], str]:
        started = time.monotonic()
        try:
            response = self._client.post(
                f"{self.settings.base_url}/chat/completions",
                json=self._body(model, request),
                headers={"Authorization": f"Bearer {self._secret}"},
                timeout=self.settings.timeout_seconds,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            raise ProviderTimeoutError(f"{model} did not answer within {self.settings.timeout_seconds:g}s") from None
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(f"could not reach OpenRouter ({type(error).__name__})") from None
        logger.info(
            "openrouter model=%s status=%d seconds=%.2f", model, response.status_code, time.monotonic() - started
        )

        payload = self._json_body(response, model)
        if response.status_code != 200 or "error" in payload:
            raise self._error(response, payload, model)
        return self._content(payload, model), str(payload.get("model") or model)

    def _json_body(self, response: httpx.Response, model: str) -> dict[str, Any]:
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ProviderUnavailableError(f"{model}: OpenRouter response exceeded {MAX_RESPONSE_BYTES} bytes")
        try:
            payload = response.json()
        except (ValueError, RecursionError):
            payload = None
        if isinstance(payload, dict):
            return payload
        if response.status_code == 200:
            raise ProviderUnavailableError(f"{model}: OpenRouter returned a response that is not a JSON object")
        return {}

    def _error(self, response: httpx.Response, payload: dict[str, Any], model: str) -> ProviderError:
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
        if status == 429:
            return ProviderRateLimitError(message, _retry_after(response))
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
