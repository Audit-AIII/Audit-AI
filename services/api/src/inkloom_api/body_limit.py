"""Request-body size limit, enforced before any route reads or parses the body (SECURITY.md).

An oversized body is refused with 413 and the standard error envelope, whether it declares its
size (`Content-Length`) or not (chunked): the body is counted as it streams, and reading stops at
the limit, so a huge or endless body cannot be buffered or parsed. Upload routes (multipart
files) get the upload limit plus 1 MB for the envelope; every other route gets the JSON limit.
"""

from __future__ import annotations

import json
import re

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .errors import ErrorCode, _body

UPLOAD_PATHS = re.compile(r"^/api/(brands/[^/]+/sources(/[^/]+/versions)?|reviews/upload)/?$")
_MESSAGE = "request body too large"


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_json_bytes: int, max_upload_bytes: int) -> None:
        self.app = app
        self.max_json_bytes = max_json_bytes
        self.max_upload_bytes = max_upload_bytes

    def limit_for(self, path: str) -> int:
        return self.max_upload_bytes if UPLOAD_PATHS.match(path) else self.max_json_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope["path"])
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True  # an unreadable length is refused, not trusted
            if too_big:
                await _reject(send)
                return

        received = 0
        started = rejected = False

        async def counted_receive() -> Message:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # Answer here: FastAPI turns an exception raised while it reads the body into
                    # its own 400, so the 413 is sent now and the app's response is dropped.
                    if not started and not rejected:
                        rejected = True
                        await _reject(send)
                    raise _TooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if rejected:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except _TooLarge:
            pass


async def _reject(send: Send) -> None:
    payload = json.dumps(_body(ErrorCode.VALIDATION_ERROR, _MESSAGE)).encode("utf-8")
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())]})
    await send({"type": "http.response.body", "body": payload})
