"""Groq adapter (OpenAI-compatible chat completions, https://console.groq.com/docs). Second in
the fallback chain (phase5 task 1).

Configuration from the environment only: `GROQ_API_KEY` (required), `GROQ_MODEL` (required —
never hard-coded; the phase doc names Llama 3.3 70B, Llama 4 or gpt-oss as options, but exact
ids on Groq's free tier change, so none is assumed here).

Uses plain `httpx`, not a Groq SDK: the API is a small, stable, OpenAI-compatible surface, and
avoiding another SDK dependency keeps this adapter's failure modes easy to reason about (same
reasoning as `inkloom_verify.providers.openrouter`, which does the same).

Structured output: Groq's `json_schema` strict mode support varies by model, so this adapter
asks for plain `response_format: {"type": "json_object"}` rather than a strict schema. The
prompt text itself (Member 2's `prompts/extraction.py` / `prompts/verification.py`) already
describes the required shape in prose, and the one-repair-retry + Pydantic validation upstream
(`extraction.py`, `verification.py`) is what actually enforces correctness — the same safety
net OpenRouter's `json_object` fallback mode relies on.
"""

from __future__ import annotations

import json
import os

import httpx
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

API_KEY_VAR = "GROQ_API_KEY"
MODEL_VAR = "GROQ_MODEL"
BASE_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=30.0)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GroqProvider:
        env = os.environ if env is None else env
        api_key = env.get(API_KEY_VAR, "").strip()
        model = env.get(MODEL_VAR, "").strip()
        missing = [name for name, value in ((API_KEY_VAR, api_key), (MODEL_VAR, model)) if not value]
        if missing:
            raise ProviderNotConfiguredError(f"Groq not configured: set {' and '.join(missing)}.")
        return cls(api_key=api_key, model=model)

    def sampling(self) -> dict:
        return {"temperature": 0.0, "seed": 0, "model": self._model}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        return with_retry(lambda: self._call(request))

    def _call(self, request: JsonCompletionRequest) -> JsonCompletion:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": 0,
            "seed": 0,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._client.post(
                BASE_URL, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
            )
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(f"Groq request timed out: {error}"[:500]) from None
        except httpx.HTTPError as error:
            raise ProviderUnavailableError(f"Groq request failed: {type(error).__name__}"[:500]) from None

        if response.status_code >= 400:
            raise self._map_status_error(response)

        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            data = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError, ValueError) as error:
            raise MalformedOutputError(f"Groq reply was not usable JSON: {type(error).__name__}"[:500]) from None
        if not isinstance(data, dict):
            raise MalformedOutputError("Groq reply was valid JSON but not an object.")

        return JsonCompletion(data=data, model=f"groq:{self._model}", attempts=1)

    @staticmethod
    def _map_status_error(response: httpx.Response) -> Exception:
        status = response.status_code
        message = f"Groq error {status}"[:500]
        if status in (401, 403):
            return ProviderAuthError(message)
        if status == 402:
            return ProviderQuotaError(message)
        if status == 429:
            return ProviderRateLimitError(message)
        if status >= 500:
            return ProviderUnavailableError(message)
        return ProviderRequestError(message)  # 400/404/413/422
