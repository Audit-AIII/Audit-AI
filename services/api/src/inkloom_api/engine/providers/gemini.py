"""Google AI Studio (Gemini) adapter. First in the fallback chain (phase5 task 1).

Configuration comes only from the environment, matching the OpenRouter adapter's own convention
(PROMPTS.md): `GEMINI_API_KEY` (required) and `GEMINI_MODEL` (required — never hard-code a model
id; free-tier models change often, and none is assumed here).
"""

from __future__ import annotations

import json
import os

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderAuthError,
    ProviderNotConfiguredError,
    ProviderQuotaError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from .retry import with_retry

API_KEY_VAR = "GEMINI_API_KEY"
MODEL_VAR = "GEMINI_MODEL"


# The SDK has its own built-in retry (HttpRetryOptions, enabled by default for 5xx/429) that
# would otherwise compound with this adapter's own `with_retry` - two independent retry loops
# multiplying delay instead of adding it, which in testing hung well past a minute on a single
# transient 503. `attempts=1` disables the SDK's layer so retry.py is the only one.
_HTTP_OPTIONS = genai_types.HttpOptions(timeout=30_000, retry_options=genai_types.HttpRetryOptions(attempts=1))


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, model: str, client: genai.Client | None = None) -> None:
        self._model = model
        self._client = client or genai.Client(api_key=api_key, http_options=_HTTP_OPTIONS)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GeminiProvider:
        env = os.environ if env is None else env
        api_key = env.get(API_KEY_VAR, "").strip()
        model = env.get(MODEL_VAR, "").strip()
        missing = [name for name, value in ((API_KEY_VAR, api_key), (MODEL_VAR, model)) if not value]
        if missing:
            raise ProviderNotConfiguredError(f"Gemini not configured: set {' and '.join(missing)}.")
        return cls(api_key=api_key, model=model)

    def sampling(self) -> dict:
        return {"temperature": 0.0, "seed": 0, "model": self._model}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        return with_retry(lambda: self._call(request))

    def _call(self, request: JsonCompletionRequest) -> JsonCompletion:
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=request.user,
                config=genai_types.GenerateContentConfig(
                    system_instruction=request.system,
                    response_mime_type="application/json",
                    response_json_schema=request.json_schema,
                    temperature=0,
                    seed=0,
                    max_output_tokens=request.max_output_tokens,
                ),
            )
        except genai_errors.ClientError as error:
            raise self._map_client_error(error) from None
        except genai_errors.ServerError as error:
            raise ProviderUnavailableError(f"Gemini server error {error.code}: {error.message}"[:500]) from None
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(f"Gemini request timed out: {error}"[:500]) from None
        except httpx.ConnectError as error:
            raise ProviderUnavailableError(f"Gemini unreachable: {error}"[:500]) from None

        text = response.text
        if not text:
            raise MalformedOutputError("Gemini returned no text content.")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise MalformedOutputError(f"Gemini reply was not valid JSON: {error}"[:500]) from None
        if not isinstance(data, dict):
            raise MalformedOutputError("Gemini reply was valid JSON but not an object.")

        return JsonCompletion(data=data, model=f"gemini:{self._model}", attempts=1)

    @staticmethod
    def _map_client_error(error: genai_errors.ClientError) -> Exception:
        code = error.code
        message = f"Gemini error {code}: {error.message}"[:500]
        if code in (401, 403):
            return ProviderAuthError(message)
        if code == 402:
            return ProviderQuotaError(message)
        if code == 429:
            return ProviderRateLimitError(message)
        return ProviderRequestError(message)  # 400/404/413/422 and anything else 4xx
