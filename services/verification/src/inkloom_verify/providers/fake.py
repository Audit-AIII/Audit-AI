"""A scripted provider for tests. Makes no network calls and reads no environment variables."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Union

from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest

Reply = Union[dict[str, Any], Exception, Callable[[JsonCompletionRequest], Union[dict[str, Any], Exception]]]


class ScriptedProvider:
    """Answers each call with the next scripted reply.

    A reply is a dict (returned as the model's JSON), an exception (raised), or a callable that
    receives the request and returns either. Every request is kept in ``calls``.
    """

    name = "fake"

    def __init__(self, *replies: Reply, model: str = "fake/model") -> None:
        self._replies = list(replies)
        self.model = model
        self.calls: list[JsonCompletionRequest] = []

    def sampling(self) -> dict[str, Any]:
        return {"temperature": 0.0, "seed": 0}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        self.calls.append(request)
        if not self._replies:
            raise AssertionError("ScriptedProvider has no reply left for this call")
        reply = self._replies.pop(0)
        if callable(reply) and not isinstance(reply, Exception):
            reply = reply(request)
        if isinstance(reply, Exception):
            raise reply
        return JsonCompletion(data=reply, model=self.model, attempts=1)
