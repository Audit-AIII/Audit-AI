"""Record a provider's replies during an evaluation run, and replay them offline.

A *cassette* is a JSONL file: one header line, then one line per call. Each call is keyed by a
hash of exactly what was asked (schema name, system prompt, user message, output limit), so a
replay answers only requests that are identical to recorded ones.

* ``RecordingProvider`` wraps a real provider and appends each reply (the parsed JSON object) or
  each provider error (its code only) to the cassette. Credentials are never written: they are
  not part of a request or a reply.
* ``ReplayProvider`` answers from a cassette, in recorded order per key. A request that was never
  recorded raises ``ReplayMissError`` (a ``ProviderError``), so the claim becomes an ERROR result
  and the run reports it. **A miss is never filled in with a made-up reply.**

Replaying the cassette of a live run reproduces that run's model answers exactly, so the
evaluation can be re-scored offline and deterministically. The header says where the replies
came from (``source``): only a cassette recorded from a live provider says anything about model
quality.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    LLMProvider,
    MalformedOutputError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from inkloom_verify.schemas import ErrorCode

CASSETTE_KIND = "inkloom-eval-cassette"
CASSETTE_VERSION = 1
_ERRORS: dict[str, type[ProviderError]] = {
    ErrorCode.PROVIDER_TIMEOUT.value: ProviderTimeoutError,
    ErrorCode.PROVIDER_RATE_LIMITED.value: ProviderRateLimitError,
    ErrorCode.MALFORMED_MODEL_OUTPUT.value: MalformedOutputError,
}


class CassetteError(ValueError):
    """The cassette file is missing, unreadable or not a cassette."""


class ReplayMissError(ProviderError):
    """The request was never recorded. Reported as a provider error; never answered with a guess."""


def request_key(request: JsonCompletionRequest) -> str:
    material = json.dumps(
        [request.schema_name, request.system, request.user, request.max_output_tokens],
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class RecordingProvider:
    """Passes every call to ``inner`` and appends what happened to ``path``."""

    def __init__(
        self, inner: LLMProvider, path: Path, metadata: dict[str, Any] | None = None
    ) -> None:
        self.inner = inner
        self.name = inner.name
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "kind": CASSETTE_KIND,
            "version": CASSETTE_VERSION,
            "source": inner.name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        } | (metadata or {})
        path.write_text(json.dumps(header, ensure_ascii=False) + "\n", encoding="utf-8")

    def sampling(self) -> dict[str, Any]:
        return self.inner.sampling()

    def _append(self, entry: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        key = request_key(request)
        try:
            completion = self.inner.complete_json(request)
        except ProviderError as error:
            self._append(
                {"key": key, "schema_name": request.schema_name, "error_code": error.code.value}
            )
            raise
        self._append(
            {
                "key": key,
                "schema_name": request.schema_name,
                "model": completion.model,
                "data": completion.data,
            }
        )
        return completion


class ReplayProvider:
    """Answers each request with the next recorded reply for the same request."""

    def __init__(self, path: Path) -> None:
        try:
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError as error:
            raise CassetteError(f"cannot read cassette {path}: {error.strerror}") from None
        try:
            entries = [json.loads(line) for line in lines]
        except json.JSONDecodeError as error:
            raise CassetteError(f"cassette {path} is not valid JSONL ({error.msg})") from None
        if (
            not entries
            or not isinstance(entries[0], dict)
            or entries[0].get("kind") != CASSETTE_KIND
        ):
            raise CassetteError(f"{path} is not an evaluation cassette")
        self.header: dict[str, Any] = entries[0]
        self.path = path
        self.sha256 = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        self.name = f"replay:{self.header.get('source', 'unknown')}"
        self._replies: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
        self._last: dict[str, dict[str, Any]] = {}
        for entry in entries[1:]:
            if (
                not isinstance(entry, dict)
                or "key" not in entry
                or ("data" not in entry and "error_code" not in entry)
            ):
                raise CassetteError(f"cassette {path} has a malformed entry")
            self._replies[entry["key"]].append(entry)
        self.misses = 0
        self.calls = 0

    @property
    def recorded_calls(self) -> int:
        return sum(len(q) for q in self._replies.values())

    def sampling(self) -> dict[str, Any]:
        return {"replay": str(self.path.name), "source": self.header.get("source")}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        self.calls += 1
        key = request_key(request)
        queue = self._replies.get(key)
        if queue:
            entry = queue.popleft()
            self._last[key] = entry
        elif key in self._last:
            entry = self._last[key]  # asked again more often than recorded: the same answer again
        else:
            self.misses += 1
            raise ReplayMissError(f"no recorded reply for this {request.schema_name} request")
        if "error_code" in entry:
            raise _ERRORS.get(entry["error_code"], ProviderUnavailableError)(
                f"recorded provider error {entry['error_code']}"
            )
        return JsonCompletion(data=entry["data"], model=entry.get("model") or "replay", attempts=1)
