"""Safe error responses.

Per docs/backend.md: every error is a stable error code, a message with no internals, and the
request ID — never a stack trace or a raw provider error. This also answers Member 2's
integration question 7 (CONTRACTS.md): FastAPI's default 422 handler echoes the offending input,
which can carry submitted content or brand-confidential source text, so it is replaced here with
one that reports only field locations and messages.
"""

from __future__ import annotations

import logging
import traceback
from enum import Enum

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException
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
    # Round 3 governance (docs/governance.md, section 8). Raised only through `ApiException`.
    SELF_APPROVAL_FORBIDDEN = "SELF_APPROVAL_FORBIDDEN"
    SELF_REVIEW_FORBIDDEN = "SELF_REVIEW_FORBIDDEN"
    SAME_REVIEWER_APPROVER_FORBIDDEN = "SAME_REVIEWER_APPROVER_FORBIDDEN"
    SELF_ROLE_CHANGE_FORBIDDEN = "SELF_ROLE_CHANGE_FORBIDDEN"
    ROLE_ESCALATION_FORBIDDEN = "ROLE_ESCALATION_FORBIDDEN"
    INVITE_EMAIL_MISMATCH = "INVITE_EMAIL_MISMATCH"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    INVITE_REVOKED = "INVITE_REVOKED"
    INVITE_ALREADY_USED = "INVITE_ALREADY_USED"
    INVITE_ALREADY_PENDING = "INVITE_ALREADY_PENDING"
    ALREADY_MEMBER = "ALREADY_MEMBER"
    LAST_OWNER_REQUIRED = "LAST_OWNER_REQUIRED"


class ApiException(HTTPException):
    """An HTTP error with its own `code`, for the cases where the status alone is not enough
    (two different 403s the frontend must tell apart). Every other error still gets its code
    from the status, exactly as before."""

    def __init__(self, status_code: int, code: ErrorCode, message: str) -> None:
        super().__init__(status_code=status_code, detail=message)
        self.code = code


class ApiError(BaseModel):
    code: ErrorCode
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ApiError


def _body(code: ErrorCode, message: str, retry_after: int | None = None) -> dict:
    body = ErrorResponse(
        error=ApiError(code=code, message=message, request_id=get_request_id())
    ).model_dump()
    if retry_after is not None:
        body["error"]["retry_after"] = retry_after  # seconds; only on 429
    return body


def internal_error_response(exc: BaseException) -> JSONResponse:
    """The safe 500 for an unhandled exception. RequestIdMiddleware (logging.py) calls it while
    the request ID is still bound, so the body and the X-Request-ID header both carry it."""
    # The type and the stack frames only: an exception's message can carry document text
    # (a pydantic ValidationError embeds its input) or a connection string.
    frames = "".join(traceback.format_tb(exc.__traceback__))
    logger.error("unhandled exception %s\n%s", type(exc).__name__, frames)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_body(ErrorCode.INTERNAL_ERROR, "an internal error occurred"),
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Field locations and error types only; never exc.errors()'s "input" (the submitted value).
        fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in exc.errors())
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_body(ErrorCode.VALIDATION_ERROR, f"invalid request: {fields}"),
        )

    # Starlette's HTTPException, which FastAPI's subclasses: this also catches the router's own
    # 404 (no such route) and 405 (wrong method), which otherwise answer a bare {"detail": ...}.
    @app.exception_handler(HTTPException)
    async def _on_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        code = getattr(exc, "code", None) or {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHENTICATED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            # No code of its own: the frontend's ApiErrorCode union is closed, and "no such route
            # for this method" is a kind of not-found. The 405 status itself is kept.
            status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.NOT_FOUND,
            status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
            status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
            status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.RATE_LIMITED,
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: ErrorCode.VALIDATION_ERROR,
        }.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        headers = dict(exc.headers or {})
        retry_after = (
            int(headers["Retry-After"])
            if exc.status_code == 429 and "Retry-After" in headers
            else None
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_body(code, message, retry_after),
            headers=headers or None,
        )

    @app.exception_handler(Exception)
    async def _on_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Normally unreachable: RequestIdMiddleware answers unhandled exceptions first. Kept as
        # the last line of defence for anything raised outside it.
        return internal_error_response(exc)
