"""Structured logging with a request ID on every line.

Every request gets a request ID (reused from the `X-Request-ID` header when the caller supplies
one, otherwise generated). It is bound to a contextvar, injected into every log record via a
`logging.Filter`, and echoed back in the `X-Request-ID` response header and in every safe error
response (see errors.py). This is the only thing that ties a client-visible failure back to a
server-side log line without ever exposing internals.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from inkloom_verify.security import install_redaction
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
# A caller's X-Request-ID is reused only if it looks like an id: it goes into every log line and
# back into responses, so free text (markup, a 5 kB string) gets a generated id instead.
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._-]{1,128}")


def get_request_id() -> str:
    return _request_id.get()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    # Every record from every logger (third-party ones included) passes through the engine's
    # redaction: registered credentials, bearer tokens and key-shaped strings become [REDACTED].
    install_redaction(handler)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s request_id=%(request_id)s %(name)s %(message)s"
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a request ID to every request and logs its outcome. No request/response bodies
    are logged: they may carry brand-confidential source material or submitted content."""

    def __init__(self, app, logger_name: str = "inkloom_api.request") -> None:
        super().__init__(app)
        self._logger = logging.getLogger(logger_name)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else uuid.uuid4().hex
        token = _request_id.set(request_id)
        try:
            self._logger.info("start method=%s path=%s", request.method, request.url.path)
            response = await call_next(request)
            self._logger.info(
                "end method=%s path=%s status=%s",
                request.method,
                request.url.path,
                response.status_code,
            )
        except Exception as exc:
            # The type only: an exception's message can carry document text or a connection
            # string. errors.py logs the stack frames (also without the message). Answered here,
            # while the request ID is still bound, so the 500 carries it like every other error.
            self._logger.error(
                "unhandled method=%s path=%s error=%s",
                request.method,
                request.url.path,
                type(exc).__name__,
            )
            from .errors import internal_error_response  # errors.py imports this module

            response = internal_error_response(exc)
        finally:
            _request_id.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response
