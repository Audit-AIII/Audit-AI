"""HTTP surface of the engine: ``POST /v1/verify``.

The backend (Member 3, ``services/api``) owns the HTTP app, authentication and tenancy, and calls
the engine in-process (contract/README.md). So the engine ships a router, not a server: the
backend mounts it with its own auth dependency and reference-set loader, and its error handlers
and request-id middleware apply unchanged.

    from inkloom_verify.api import create_verify_router
    app.include_router(create_verify_router(
        engine, authenticated_tenant=tenant_of_membership, reference_set_loader=approved_documents))

The request and response are the public contract (``api_contract.VerifyRequest`` and
``api_contract.Report``, CONTRACTS.md "Public API contract"). The request names a
``reference_set_id`` but carries no documents and no tenant: the tenant comes only from
authentication, and ``reference_set_loader(tenant, reference_set_id)`` returns that tenant's
documents for the set.

``create_dev_app`` serves the same router on its own for local development and tests only. It has
no authentication, so it must never be exposed.

Errors use the approved envelope ``{"error": {"code", "message", "request_id"}}``, plus
``retry_after`` (whole seconds, also the ``Retry-After`` header) on 429 only. Messages are fixed
per code: nothing from a provider, a document or the request is echoed.

* malformed JSON, a schema violation, empty or over-long content, or an over-size body: 400
  ``INVALID_INPUT``, listing field locations only (handled by this router, whatever the host app's
  own validation handler does);
* a ``reference_set_id`` the loader does not know (None), including another tenant's: 404
  ``REFERENCE_SET_NOT_FOUND``, the same answer either way;
* a known reference set with no documents (an empty list): 409 ``REFERENCE_SET_EMPTY``;
* a run that produced no results, by its engine error code: model output still invalid after
  the repair attempt, 422 ``UNPARSEABLE_MODEL_OUTPUT``; provider rate limit, 429 ``RATE_LIMITED``;
  provider timeout, 504 ``PROVIDER_TIMEOUT``; an unexpected engine failure, 500
  ``INTERNAL_ERROR``; anything else (provider not configured, quota, provider error, budget),
  503 with the engine's code;
* anything else unexpected, including a report that does not answer its request: 500
  ``INTERNAL_ERROR`` from the host app's handler.

A run with results is a 200 Report even when some claims failed (ERROR verdicts) or some
sentences went unchecked (``metadata.errors``).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import ValidationError
from starlette.responses import JSONResponse

from inkloom_verify import __version__
from inkloom_verify.api_contract import NotRepresentable, Report, VerifyRequest, to_public_report
from inkloom_verify.schemas import (
    MAX_CONTENT_CHARS,
    ErrorCode,
    ReferenceDocument,
    ReportStatus,
    VerificationReport,
    VerificationRequest,
)
from inkloom_verify.scope import check_report_scope

logger = logging.getLogger(__name__)

ENGINE_MODE_HEADER = "X-Inkloom-Engine-Mode"
ENGINE_MODE_VAR = "INKLOOM_ENGINE_MODE"
# Largest body worth parsing: the content limit, plus generous room for JSON escaping and options.
MAX_BODY_BYTES = 6 * MAX_CONTENT_CHARS + 64_000
# The tenant the unauthenticated development app works as. Never used when a backend mounts the
# router with authentication.
DEV_TENANT = "dev-unauthenticated"

ReferenceSetLoader = Callable[[str, str], Sequence[ReferenceDocument] | None]
DEFAULT_RETRY_AFTER_SECONDS = 30

# A run with no results, by the engine's error code -> (HTTP status, public code, fixed message).
# Codes not listed answer 503 with the engine's own code.
FAILED_RUN_ERRORS: dict[ErrorCode, tuple[int, str, str]] = {
    ErrorCode.MALFORMED_MODEL_OUTPUT: (422, "UNPARSEABLE_MODEL_OUTPUT",
                                       "The AI model's output was still invalid after the repair attempt."),
    ErrorCode.PROVIDER_RATE_LIMITED: (429, "RATE_LIMITED", "The AI provider is rate limiting requests; retry later."),
    ErrorCode.PROVIDER_TIMEOUT: (504, "PROVIDER_TIMEOUT", "The AI provider did not answer within the configured timeout."),
    ErrorCode.INTERNAL_ERROR: (500, "INTERNAL_ERROR", "an internal error occurred"),
}
OTHER_FAILURE_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.PROVIDER_NOT_CONFIGURED: "No AI provider is configured, so no checks could run.",
    ErrorCode.PROVIDER_QUOTA_EXCEEDED: "The AI provider account has no remaining quota.",
    ErrorCode.PROVIDER_ERROR: "The AI provider could not complete the request.",
    ErrorCode.LIMIT_EXCEEDED: "The request reached its processing limit before any claim was checked.",
}


class VerificationEngine(Protocol):
    """What the endpoint calls. ``mode`` is reported in the X-Inkloom-Engine-Mode header."""

    mode: str

    def verify(
        self, request: VerificationRequest, *, suggest_corrections: bool = True, max_claims: int | None = None
    ) -> VerificationReport: ...


async def _limit_body_size(request: Request) -> None:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise RequestValidationError([{"loc": ("body",), "msg": "request body too large", "type": "too_large"}])


def _engine_error(
    http_status: int, code: str, message: str, request_id: str, mode: str | None = None, retry_after: int | None = None
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    headers = {ENGINE_MODE_HEADER: mode} if mode else {}
    if retry_after is not None:
        error["retry_after"] = retry_after
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(status_code=http_status, content={"error": error}, headers=headers)


def _failed_run(report: VerificationReport, request_id: str, mode: str, default_retry_after: int) -> JSONResponse:
    """The HTTP error for a run with no results, by the engine's first error code."""
    first = report.errors[0] if report.errors else None
    code = first.code if first else ErrorCode.INTERNAL_ERROR
    if code in FAILED_RUN_ERRORS:
        http_status, public_code, message = FAILED_RUN_ERRORS[code]
    else:
        http_status, public_code = status.HTTP_503_SERVICE_UNAVAILABLE, code.value
        message = OTHER_FAILURE_MESSAGES.get(code, "The verification engine is unavailable.")
    retry_after = None
    if http_status == 429:
        retry_after = first.retry_after_seconds if first and first.retry_after_seconds is not None else default_retry_after
    return _engine_error(http_status, public_code, message, request_id, mode, retry_after)


def create_verify_router(
    engine: VerificationEngine,
    *,
    reference_set_loader: ReferenceSetLoader,
    authenticated_tenant: Callable[..., Any] | None = None,
    max_content_chars: int = MAX_CONTENT_CHARS,
    allow_unauthenticated: bool = False,
    request_id_provider: Callable[[], str] | None = None,
    default_retry_after: int = DEFAULT_RETRY_AFTER_SECONDS,
) -> APIRouter:
    """The ``POST /v1/verify`` router.

    ``authenticated_tenant`` is a FastAPI dependency returning the caller's tenant id as the
    backend authenticated it (for Member 3: the organisation id from ``get_current_membership``).
    It is required unless ``allow_unauthenticated`` is set, which only the development app does.

    ``reference_set_loader(tenant_id, reference_set_id)`` is the backend's: it returns the
    documents of that set if the tenant may use it, and None or nothing otherwise (404). The engine
    has no database and cannot decide either. An exception from it is a 500: access fails closed.

    ``max_content_chars`` is the configurable content limit, at most the contract's
    MAX_CONTENT_CHARS.

    ``request_id_provider`` returns the host app's request id for errors raised before the body is
    valid (Member 3: ``inkloom_api.logging.get_request_id``). Without it, the incoming
    ``X-Request-ID`` header is used, else a new id. Errors after validation use the body's
    ``request_id``.

    ``default_retry_after`` is the 429 ``retry_after`` when the provider gave none.
    """
    if authenticated_tenant is None and not allow_unauthenticated:
        raise ValueError("create_verify_router needs authenticated_tenant; only the development app may omit it")
    if not 1 <= max_content_chars <= MAX_CONTENT_CHARS:
        raise ValueError(f"max_content_chars must be between 1 and {MAX_CONTENT_CHARS}")
    if not 0 <= default_retry_after <= 3_600:
        raise ValueError("default_retry_after must be between 0 and 3600 seconds")

    def invalid_input(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(part) for part in e["loc"]) for e in exc.errors()) or "body"
        request_id = (request_id_provider() if request_id_provider else None) or request.headers.get("x-request-id") or str(uuid.uuid4())
        return _engine_error(status.HTTP_400_BAD_REQUEST, "INVALID_INPUT", f"invalid request: {fields}", request_id)

    class VerifyRoute(APIRoute):
        """Answers this route's validation errors itself (400 INVALID_INPUT), so the result is the
        same in any host app, whatever its own RequestValidationError handler returns."""

        def get_route_handler(self) -> Callable[..., Any]:
            handler = super().get_route_handler()

            async def route(request: Request) -> Any:
                try:
                    return await handler(request)
                except RequestValidationError as exc:
                    return invalid_input(request, exc)

            return route

    router = APIRouter(tags=["verification"], route_class=VerifyRoute)
    tenant_dependency = authenticated_tenant or (lambda: None)

    @router.post(
        "/v1/verify",
        response_model=Report,
        dependencies=[Depends(_limit_body_size)],
        summary="Verify the claims in one piece of content against an approved reference set",
        responses={
            400: {"description": "INVALID_INPUT: malformed or invalid request"},
            404: {"description": "REFERENCE_SET_NOT_FOUND: not a reference set the authenticated tenant can use"},
            409: {"description": "REFERENCE_SET_EMPTY: the reference set has no documents"},
            422: {"description": "UNPARSEABLE_MODEL_OUTPUT: model output invalid after the repair attempt"},
            429: {"description": "RATE_LIMITED: provider rate limit; retry_after says when to retry"},
            503: {"description": "the engine produced no results for another reason (error code says why)"},
            504: {"description": "PROVIDER_TIMEOUT: the provider did not answer in time"},
        },
    )
    def verify(body: VerifyRequest, tenant: Any = Depends(tenant_dependency)) -> Any:
        if len(body.content.text) > max_content_chars:
            raise RequestValidationError(
                [{"loc": ("body", "content", "text"), "msg": f"content is longer than {max_content_chars} characters",
                  "type": "too_long"}]
            )
        if engine.mode == "fake":
            # Canned verdicts never reach a public Report, which cannot say they are fake.
            return _engine_error(status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.PROVIDER_NOT_CONFIGURED.value,
                                 "No AI provider is configured; the development engine does not return results here.",
                                 body.request_id, engine.mode)
        tenant_id = DEV_TENANT if tenant is None else str(tenant)
        documents = reference_set_loader(tenant_id, body.reference_set_id)
        if documents is None:  # unknown, or not this tenant's: the same answer
            return _engine_error(status.HTTP_404_NOT_FOUND, "REFERENCE_SET_NOT_FOUND", "reference set not found",
                                 body.request_id, engine.mode)
        if len(documents) == 0:
            return _engine_error(status.HTTP_409_CONFLICT, "REFERENCE_SET_EMPTY",
                                 "the reference set has no documents to check against", body.request_id, engine.mode)
        try:
            request = VerificationRequest(
                request_id=body.request_id, tenant_id=tenant_id, reference_set_id=body.reference_set_id,
                content={"content_id": body.content.id, "text": body.content.text}, references=list(documents),
            )
        except ValidationError:
            # The backend's documents, not the caller's request, broke the contract (too many,
            # too long, a wrong hash). Field locations only: the documents are confidential.
            logger.error("verify request=%s reference set %s is unusable", body.request_id, body.reference_set_id)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "the reference set could not be used") from None

        # Corrections need the request's option AND the server's setting (approved, prompts Phase 4).
        corrections = body.options.suggest_corrections and getattr(engine, "corrections_enabled", True)
        report = engine.verify(request, suggest_corrections=corrections, max_claims=body.options.max_claims)
        # Whatever engine is plugged in, a report that does not answer this request (other tenant,
        # other documents, foreign evidence) never leaves the endpoint: ScopeViolation is a 500.
        check_report_scope(request, report)
        logger.info("verify request=%s mode=%s status=%s claims=%d",
                    body.request_id, engine.mode, report.status.value, len(report.results))
        if report.status is ReportStatus.FAILED:
            return _failed_run(report, body.request_id, engine.mode, default_retry_after)
        try:
            public = to_public_report(report, suggest_corrections=corrections)
        except NotRepresentable as problem:
            logger.error("verify request=%s report not representable: %s", body.request_id, type(problem).__name__)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "the engine's result could not be returned") from None
        data = public.model_dump(mode="json")
        if body.options.suggest_corrections and not corrections:  # asked for, but off on this server: say so
            data["metadata"]["errors"].append({"code": ErrorCode.INVALID_REQUEST.value,
                                               "message": "Corrections were requested but are disabled on this server."})
            Report.model_validate(data, context={"suggest_corrections": False})
        # Already validated as a public Report with the options that applied: returned as JSON
        # directly, so it is not re-validated without them.
        return JSONResponse(data, headers={ENGINE_MODE_HEADER: engine.mode})

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


EXAMPLE_REQUEST = Path(__file__).resolve().parents[2] / "examples" / "verification_request.json"


def example_reference_sets() -> ReferenceSetLoader:
    """DEVELOPMENT ONLY: one in-memory reference set, the example documents of
    examples/verification_request.json under its reference_set_id, for DEV_TENANT. Anything else
    is not found."""
    sets: dict[tuple[str, str], list[ReferenceDocument]] = {}
    if EXAMPLE_REQUEST.exists():
        example = json.loads(EXAMPLE_REQUEST.read_text(encoding="utf-8"))
        sets[(DEV_TENANT, example["reference_set_id"])] = [ReferenceDocument.model_validate(d) for d in example["references"]]

    def load(tenant_id: str, reference_set_id: str) -> list[ReferenceDocument] | None:
        return sets.get((tenant_id, reference_set_id))

    return load


def create_dev_app(engine: VerificationEngine | None = None, reference_set_loader: ReferenceSetLoader | None = None) -> FastAPI:
    """A standalone app serving /v1/verify, for local development and tests. No authentication.

    Without an explicit ``engine`` it reads INKLOOM_ENGINE_MODE, which must be set:

    * ``live``: the real engine (OpenRouter; needs OPENROUTER_API_KEY and INKLOOM_LLM_MODELS). If
      those are missing, startup fails with the configuration message, not on the first request.
    * ``fake``: the development engine. Through the public endpoint it answers 503
      PROVIDER_NOT_CONFIGURED: its canned verdicts are never returned as a Report.

    Without a ``reference_set_loader`` it serves the example reference set (``example_reference_sets``).
    """
    if engine is None:
        mode = os.environ.get(ENGINE_MODE_VAR, "").strip().lower()
        if mode == "live":
            from inkloom_verify.pipeline import PipelineEngine
            from inkloom_verify.providers.openrouter import OpenRouterProvider

            engine = PipelineEngine(OpenRouterProvider.from_env())  # raises ProviderNotConfiguredError
        elif mode == "fake":
            from inkloom_verify.fake_engine import FakeEngine

            engine = FakeEngine()
        else:
            raise RuntimeError(
                f"{ENGINE_MODE_VAR} is {mode or 'unset'}. Set {ENGINE_MODE_VAR}=live for the real engine, "
                f"or {ENGINE_MODE_VAR}=fake for the development engine."
            )
    app = FastAPI(
        title="INKLOOM verification engine (development)",
        version=__version__,
        description="Development server for POST /v1/verify. No authentication: never expose it.",
    )
    install_dev_error_handlers(app)
    app.include_router(create_verify_router(engine, reference_set_loader=reference_set_loader or example_reference_sets(),
                                            allow_unauthenticated=True))
    return app
