"""HTTP surface of the engine: ``POST /v1/verify``.

The backend (Member 3, ``services/api``) owns the HTTP app, authentication and tenancy, and calls
the engine in-process (contract/README.md). So the engine ships a router, not a server: the
backend mounts it with its own auth dependency, and its error handlers and request-id middleware
apply unchanged.

    from inkloom_verify.api import create_verify_router
    app.include_router(create_verify_router(engine, authenticated_tenant=tenant_of_membership))

``create_dev_app`` serves the same router on its own for local development and tests only. It has
no authentication, so it must never be exposed.

Errors use the backend's shape, ``{"error": {"code", "message", "request_id"}}``:

* malformed JSON, a schema violation or an over-size body: 422 ``VALIDATION_ERROR``, listing field
  locations only, never the submitted values;
* a body ``tenant_id`` that is not the authenticated tenant: 403 ``FORBIDDEN``;
* anything unexpected: 500 ``INTERNAL_ERROR``.

A processing failure inside the engine (provider down, malformed model output, ...) is not an
HTTP error: the 200 response carries a report whose ``status`` is PARTIAL or FAILED and whose
``errors`` say what went wrong (CONTRACTS.md, Reports).
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from inkloom_verify import __version__
from inkloom_verify.schemas import MAX_CONTENT_CHARS, MAX_TOTAL_REFERENCE_CHARS, VerificationReport, VerificationRequest
from inkloom_verify.scope import check_report_scope

logger = logging.getLogger(__name__)

ENGINE_MODE_HEADER = "X-Inkloom-Engine-Mode"
ENGINE_MODE_VAR = "INKLOOM_ENGINE_MODE"
# Largest body worth parsing: the contract's text limits, plus generous room for JSON overhead.
MAX_BODY_BYTES = 4 * (MAX_CONTENT_CHARS + MAX_TOTAL_REFERENCE_CHARS) + 1_000_000


class VerificationEngine(Protocol):
    """What the endpoint calls. ``mode`` is reported in the X-Inkloom-Engine-Mode header."""

    mode: str

    def verify(self, request: VerificationRequest) -> VerificationReport: ...


async def _limit_body_size(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise RequestValidationError([{"loc": ("body",), "msg": "request body too large", "type": "too_large"}])


def create_verify_router(
    engine: VerificationEngine,
    *,
    authenticated_tenant: Callable[..., Any] | None = None,
) -> APIRouter:
    """The ``POST /v1/verify`` router.

    ``authenticated_tenant`` is a FastAPI dependency returning the caller's tenant id as the
    backend authenticated it (for Member 3: the organisation id from ``get_current_membership``).
    When given, a request whose ``tenant_id`` differs is refused with 403. When omitted, nothing
    authenticates the caller: only the development app does that.
    """
    router = APIRouter(tags=["verification"])
    tenant_dependency = authenticated_tenant or (lambda: None)

    @router.post(
        "/v1/verify",
        response_model=VerificationReport,
        response_model_exclude_none=True,
        dependencies=[Depends(_limit_body_size)],
        summary="Verify the claims in one piece of content against its reference documents",
        responses={
            403: {"description": "tenant_id is not the authenticated tenant"},
            422: {"description": "malformed or invalid request"},
        },
    )
    def verify(
        body: VerificationRequest,
        response: Response,
        tenant: Any = Depends(tenant_dependency),
    ) -> VerificationReport:
        if tenant is not None and body.tenant_id != str(tenant):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "tenant_id does not match the authenticated organisation")
        response.headers[ENGINE_MODE_HEADER] = engine.mode
        report = engine.verify(body)
        # Responses are validated too: whatever engine is plugged in, a report that does not answer
        # this request (other tenant, other documents, foreign evidence) never leaves the endpoint.
        check_report_scope(body, report)
        logger.info(
            "verify request=%s mode=%s status=%s claims=%d",
            body.request_id, engine.mode, report.status.value, len(report.results),
        )
        return report

    return router


# --- Development app (no authentication: never expose it) -------------------------------------


def _error(code: str, message: str, request: Request, http_status: int) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    return JSONResponse(status_code=http_status, content={"error": {"code": code, "message": message, "request_id": request_id}})


def install_dev_error_handlers(app: FastAPI) -> None:
    """The backend's error shape and mapping (services/api errors.py), for the development app.
    Inside the backend, its own handlers apply instead; a test checks the two agree."""

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in exc.errors())
        return _error("VALIDATION_ERROR", f"invalid request: {fields}", request, status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(HTTPException)
    async def _http(request: Request, exc: HTTPException) -> JSONResponse:
        code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT"}.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return _error(code, message, request, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled exception: %s", type(exc).__name__)  # the type only: messages may hold content
        return _error("INTERNAL_ERROR", "an internal error occurred", request, status.HTTP_500_INTERNAL_SERVER_ERROR)


def create_dev_app(engine: VerificationEngine | None = None) -> FastAPI:
    """A standalone app serving /v1/verify, for local development and tests. No authentication.

    Without an explicit ``engine`` it reads INKLOOM_ENGINE_MODE. In Phase 2 the only engine is the
    fake one, and it must be asked for (INKLOOM_ENGINE_MODE=fake): canned results are never served
    by default.
    """
    if engine is None:
        mode = os.environ.get(ENGINE_MODE_VAR, "").strip().lower()
        if mode != "fake":
            raise RuntimeError(
                f"{ENGINE_MODE_VAR} is {mode or 'unset'}. The only engine available in this phase is the "
                f"canned development engine; set {ENGINE_MODE_VAR}=fake to serve it."
            )
        from inkloom_verify.fake_engine import FakeEngine

        engine = FakeEngine()
    app = FastAPI(
        title="INKLOOM verification engine (development)",
        version=__version__,
        description="Development server for POST /v1/verify. No authentication: never expose it.",
    )
    install_dev_error_handlers(app)
    app.include_router(create_verify_router(engine))
    return app
