"""The engine's single entry point: one VerificationRequest in, one VerificationReport out.

    plain text -> claim extraction -> per-claim retrieval -> per-claim verification
    -> citation guard -> correction of CONTRADICTED claims -> scored, scope-checked report

The backend calls ``verify_request`` in-process (contract/README.md). It never raises for a
problem with the content, the model or the provider: those become ERROR results, request-level
errors and a PARTIAL or FAILED status, so a caller can never mistake a failure for a clean
result. A report that fails its own scope check is replaced by a FAILED report.

Command line, for manual runs against a live provider:

    PYTHONPATH=src python -m inkloom_verify.pipeline --request request.json --out report.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from inkloom_verify import __version__
from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.correction import ClaimCorrector, CorrectionConfig
from inkloom_verify.extraction import ClaimExtractor, ExtractionConfig, ExtractionResult, WarningCode
from inkloom_verify.prompts import correction as correction_prompt
from inkloom_verify.prompts import extraction as extraction_prompt
from inkloom_verify.prompts import verification as verification_prompt
from inkloom_verify.providers.base import LLMProvider, ProviderError
from inkloom_verify.providers.budget import BudgetedProvider, CallBudget
from inkloom_verify.retrieval import BM25Retriever, RetrievalConfig
from inkloom_verify.schemas import (
    Claim,
    ClaimResult,
    CorrectionAttempt,
    CorrectionStatus,
    EngineProvenance,
    ErrorCode,
    PipelineStage,
    ProcessingError,
    ReportScore,
    ReportStatus,
    RetrievalMethod,
    Verdict,
    VerificationReport,
    VerificationRequest,
)
from inkloom_verify.scope import ScopeViolation, check_report_scope
from inkloom_verify.verification import ClaimVerifier, VerificationConfig, verify_claim

logger = logging.getLogger(__name__)

PROMPT_VERSIONS = {
    "extract_claims": extraction_prompt.PROMPT_VERSION,
    "verify_claim": verification_prompt.PROMPT_VERSION,
    "correct_claim": correction_prompt.PROMPT_VERSION,
}


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    correction: CorrectionConfig = Field(default_factory=CorrectionConfig)
    correct_contradicted: bool = True
    # Per-request limits on model calls, estimated tokens and wall-clock time (providers/budget.py).
    budget: CallBudget = Field(default_factory=CallBudget)


def verify_request(
    request: VerificationRequest, provider: LLMProvider, config: PipelineConfig | None = None
) -> VerificationReport:
    """Runs the full workflow for one request. All evidence comes from ``request.references``."""
    config = config or PipelineConfig()
    models: set[str] = set()
    budgeted = BudgetedProvider(provider, config.budget)
    try:
        results, errors = _run(request, budgeted, config, models)
        report = _report(request, provider, results, errors, models)
        check_report_scope(request, report)
        logger.info("pipeline request=%s usage=%s", request.request_id, budgeted.usage())
        return report
    except ScopeViolation as violation:
        # Ids only (never text), so the violations are safe to log.
        logger.error("pipeline request=%s scope violation: %s", request.request_id, violation.violations[:5])
        return _failed(request, provider, models, "The report did not match its request and was discarded.")
    except Exception as error:  # noqa: BLE001 - never fail open; the type name is safe to log, the message may not be
        logger.error("pipeline request=%s failed unexpectedly: %s", request.request_id, type(error).__name__)
        return _failed(request, provider, models, "The verification engine failed unexpectedly.")


def _run(
    request: VerificationRequest, provider: LLMProvider, config: PipelineConfig, models: set[str]
) -> tuple[list[ClaimResult], list[ProcessingError]]:
    extraction = ClaimExtractor(provider, config.extraction).extract(request.content)
    models.update(extraction.provenance.models)
    errors = list(extraction.errors) + _unchecked_sentences(extraction)

    retriever = BM25Retriever.for_request(request, chunking=config.chunking, config=config.retrieval)
    verifier = ClaimVerifier(provider, request.references, config.verification)
    corrector = (
        ClaimCorrector(provider, verifier if config.correction.recheck else None, config.correction)
        if config.correct_contradicted
        else None
    )
    results = []
    for claim in extraction.claims:
        # Partial failure (Phase 4): a claim's own failure stays with that claim. Provider errors
        # already become ERROR results inside the verifier; anything unexpected is caught here, so
        # it can neither erase nor change any other claim's result. (A scope violation is still
        # checked over the whole report afterwards: contamination is not safe to continue past.)
        try:
            result = verify_claim(claim, retriever, verifier, top_k=config.retrieval.top_k)
        except Exception as error:  # noqa: BLE001 - the type name is safe to log, the message may hold content
            logger.error("pipeline request=%s claim=%s verification failed unexpectedly: %s",
                         request.request_id, claim.claim_id, type(error).__name__)
            result = _claim_error(claim, PipelineStage.VERIFICATION)
        if corrector is not None and result.verdict is Verdict.CONTRADICTED:
            try:
                result = corrector.correct(result, request.content)
            except Exception as error:  # noqa: BLE001
                logger.error("pipeline request=%s claim=%s correction failed unexpectedly: %s",
                             request.request_id, claim.claim_id, type(error).__name__)
                result = _correction_failed(result)
        results.append(result)
    models.update(verifier.models_used)
    if corrector is not None:
        models.update(corrector.models_used)
    logger.info(
        "pipeline request=%s claims=%d errors=%d verdicts=%s",
        request.request_id, len(results), len(errors),
        ",".join(f"{v.value}:{sum(r.verdict is v for r in results)}" for v in Verdict),
    )
    return results, errors


def _claim_error(claim: Claim, stage: PipelineStage) -> ClaimResult:
    """An ERROR result for one claim whose processing failed unexpectedly: no evidence, no verdict."""
    return ClaimResult(
        claim=claim,
        verdict=Verdict.ERROR,
        error=ProcessingError(
            code=ErrorCode.INTERNAL_ERROR, stage=stage, retryable=False, claim_id=claim.claim_id,
            message="This claim could not be checked because of an internal error.",
        ),
    )


def _correction_failed(result: ClaimResult) -> ClaimResult:
    """The verdict stands; the correction attempt is recorded as FAILED (as for a provider failure)."""
    attempt = CorrectionAttempt(
        status=CorrectionStatus.FAILED,
        error=ProcessingError(
            code=ErrorCode.INTERNAL_ERROR, stage=PipelineStage.CORRECTION, retryable=False, claim_id=result.claim.claim_id,
            message="No correction could be proposed because of an internal error.",
        ),
    )
    data = result.model_dump()
    data.update(correction=None, correction_attempt=attempt.model_dump())
    data.pop("requires_human_review", None)  # re-derived
    data.pop("evidence_strength", None)
    return ClaimResult.model_validate(data)


def _unchecked_sentences(extraction: ExtractionResult) -> list[ProcessingError]:
    """Sentences the model skipped were never checked: say so, rather than report them as clean."""
    skipped = sum(1 for w in extraction.warnings if w.code is WarningCode.SENTENCE_NOT_CLASSIFIED)
    if not skipped:
        return []
    return [
        ProcessingError(
            code=ErrorCode.MALFORMED_MODEL_OUTPUT,
            stage=PipelineStage.EXTRACTION,
            message=f"{skipped} sentence(s) were not classified by the model and were not checked.",
            retryable=True,
        )
    ]


def _status(results: list[ClaimResult], errors: list[ProcessingError]) -> ReportStatus:
    if not results and errors:
        return ReportStatus.FAILED
    if errors or any(r.verdict is Verdict.ERROR for r in results):
        return ReportStatus.PARTIAL
    return ReportStatus.COMPLETED


def _provenance(provider: LLMProvider, models: set[str]) -> EngineProvenance:
    return EngineProvenance(
        engine_version=__version__,
        retrieval_method=RetrievalMethod.BM25,
        provider=provider.name,
        model_id=_model_ids(models),
        prompt_versions=PROMPT_VERSIONS,
    )


def _model_ids(models: set[str]) -> str | None:
    """Every model that answered, comma-separated, within the 64-character field; whole ids only."""
    joined = ""
    for model in sorted(models):
        candidate = f"{joined},{model}" if joined else model
        if len(candidate) > 64:
            return (joined + ",+") if joined and len(joined) <= 62 else joined or None
        joined = candidate
    return joined or None


def _report(
    request: VerificationRequest,
    provider: LLMProvider,
    results: list[ClaimResult],
    errors: list[ProcessingError],
    models: set[str],
) -> VerificationReport:
    return VerificationReport(
        request_id=request.request_id,
        tenant_id=request.tenant_id,
        reference_set_id=request.reference_set_id,
        content_sha256=request.content.text_sha256,
        content_length=len(request.content.text),
        references=[d.descriptor() for d in request.references],
        status=_status(results, errors),
        results=results,
        errors=errors,
        provenance=_provenance(provider, models),
        score=ReportScore.compute(results, errors),
    )


def _failed(request: VerificationRequest, provider: LLMProvider, models: set[str], message: str) -> VerificationReport:
    error = ProcessingError(
        code=ErrorCode.INTERNAL_ERROR, stage=PipelineStage.REQUEST, message=message, retryable=False
    )
    return _report(request, provider, [], [error], models)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inkloom_verify.pipeline", description=__doc__)
    parser.add_argument("--request", type=Path, required=True, help="VerificationRequest JSON file")
    parser.add_argument("--out", type=Path, help="write the VerificationReport JSON here (default: stdout)")
    args = parser.parse_args(argv)
    try:
        from inkloom_verify.providers.openrouter import OpenRouterProvider

        request = VerificationRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        provider = OpenRouterProvider.from_env()
    except ProviderError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        # A ValidationError's text embeds the input; show only its class.
        print(f"error: could not read the request ({type(error).__name__})", file=sys.stderr)
        return 2
    report = verify_request(request, provider)
    payload = report.model_dump_json(indent=2, exclude_none=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())


class PipelineEngine:
    """The real engine behind POST /v1/verify (the VerificationEngine protocol in api.py):
    extraction, retrieval, verification, the citation guard, and (since Phase 5) minimal,
    re-checked corrections of CONTRADICTED claims."""

    mode = "live"

    def __init__(self, provider: LLMProvider, config: PipelineConfig | None = None) -> None:
        self.provider = provider
        self.config = config or PipelineConfig()

    def verify(
        self, request: VerificationRequest, *, suggest_corrections: bool = True, max_claims: int | None = None
    ) -> VerificationReport:
        """``suggest_corrections`` and ``max_claims`` are the request's options (POST /v1/verify)."""
        extraction = self.config.extraction
        if max_claims is not None:
            extraction = extraction.model_copy(update={"max_claims": min(max_claims, extraction.max_claims)})
        config = self.config.model_copy(update={"correct_contradicted": suggest_corrections, "extraction": extraction})
        return verify_request(request, self.provider, config)
