"""Safe error responses.

Per 00_CONTEXT.md: every error is a stable error code, a message with no internals, and the
request ID — never a stack trace or a raw provider error. This also answers Member 2's
integration question 7 (CONTRACTS.md): FastAPI's default 422 handler echoes the offending input,
which can carry submitted content or brand-confidential source text, so it is replaced here with
one that reports only field locations and messages.
"""

from __future__ import annotations

import logging
import traceback
from enum import Enum

from fastapi import FastAPI, HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import JSONResponse

from .logging import get_request_id

logger = logging.getLogger("inkloom_api.errors")


class ErrorCode(str, Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(BaseModel):
    code: ErrorCode
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ApiError


def _body(code: ErrorCode, message: str, retry_after: int | None = None) -> dict:
    body = ErrorResponse(error=ApiError(code=code, message=message, request_id=get_request_id())).model_dump()
    if retry_after is not None:
        body["error"]["retry_after"] = retry_after  # seconds; only on 429
    return body


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and error types only; never exc.errors()'s "input" (the submitted value).
        fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body(ErrorCode.VALIDATION_ERROR, f"invalid request: {fields}"),
        )

    @app.exception_handler(HTTPException)
    async def _on_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        code = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
            status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
            status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: ErrorCode.VALIDATION_ERROR,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        headers = dict(exc.headers or {})
        retry_after = int(headers["Retry-After"]) if exc.status_code == 429 and "Retry-After" in headers else None
        return JSONResponse(status_code=exc.status_code, content=_body(code, message, retry_after), headers=headers or None)

    @app.exception_handler(Exception)
    async def _on_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # The type and the stack frames only: an exception's message can carry document text
        # (a pydantic ValidationError embeds its input) or a connection string.
        frames = "".join(traceback.format_tb(exc.__traceback__))
        logger.error("unhandled exception %s\n%s", type(exc).__name__, frames)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_body(ErrorCode.INTERNAL_ERROR, "an internal error occurred"),
        )
