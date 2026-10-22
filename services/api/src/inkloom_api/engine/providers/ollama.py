"""Local Ollama adapter (https://github.com/ollama/ollama/blob/main/docs/api.md). Last in the
fallback chain (phase5 task 1), and the only one usable for confidential sources (task 8 — no
content leaves the machine).

Configuration from the environment: `OLLAMA_BASE_URL` (optional, defaults to the standard local
address) and `OLLAMA_MODEL` (required — depends entirely on what the operator has pulled
locally, so there is no sensible default to assume).
"""

from __future__ import annotations

import json
import os

import httpx
from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderNotConfiguredError,
    ProviderRequestError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

from .retry import with_retry

BASE_URL_VAR = "OLLAMA_BASE_URL"
MODEL_VAR = "OLLAMA_MODEL"
DEFAULT_BASE_URL = "http://localhost:11434"


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, client: httpx.Client | None = None) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=60.0)  # local models can be slow to load

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> OllamaProvider:
        env = os.environ if env is None else env
        model = env.get(MODEL_VAR, "").strip()
        if not model:
            raise ProviderNotConfiguredError(f"Ollama not configured: set {MODEL_VAR}.")
        base_url = env.get(BASE_URL_VAR, "").strip() or DEFAULT_BASE_URL
        return cls(base_url=base_url, model=model)

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
            "format": "json",
            "stream": False,
            "options": {"temperature": 0, "seed": 0, "num_predict": request.max_output_tokens},
        }
        try:
            response = self._client.post(f"{self._base_url}/api/chat", json=body)
        except httpx.TimeoutException as error:
            raise ProviderTimeoutError(f"Ollama request timed out: {error}"[:500]) from None
        except httpx.HTTPError as error:
            # Includes connection-refused (server not running) - never a config problem by
            # itself, since OLLAMA_MODEL was set; the server just isn't reachable right now.
            raise ProviderUnavailableError(f"Ollama unreachable: {type(error).__name__}"[:500]) from None

        if response.status_code >= 400:
            if response.status_code == 404:
                raise ProviderRequestError(f"Ollama model not found: {self._model}"[:500])
            raise ProviderUnavailableError(f"Ollama error {response.status_code}"[:500])

        try:
            payload = response.json()
            content = payload["message"]["content"]
            data = json.loads(content)
        except (KeyError, json.JSONDecodeError, ValueError) as error:
            raise MalformedOutputError(f"Ollama reply was not usable JSON: {type(error).__name__}"[:500]) from None
        if not isinstance(data, dict):
            raise MalformedOutputError("Ollama reply was valid JSON but not an object.")

        return JsonCompletion(data=data, model=f"ollama:{self._model}", attempts=1)
