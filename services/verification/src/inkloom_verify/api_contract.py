"""The public API contract: Claim, Passage, Evidence, Verdict and Report, as specified for callers.

A layer over the engine's internal contract (``schemas.py``, 0.2.0), which Member 3's backend
imports and stays unchanged. ``to_public_report`` maps an internal report to this shape. Approved
decisions (2026-10-23, CONTRACTS.md "Public API contract"):

* every model carries ``schema_version``;
* ``Verdict.confidence`` is a fixed map of the engine's evidence strength (none 0.0, weak 0.33,
  moderate 0.67, strong 1.0): an ordinal score computed by rules, **not a calibrated
  probability**, and never raised by anything a model says;
* ``Report.metadata`` holds ``content_hash`` only;
* ``suggest_corrections`` is a request option, default true. When true, every CONTRADICTED
  verdict carries a correction outcome: a proposed correction, or an explicit
  ``needs_human_review``/``failed`` outcome with no replacement (never an invented one). When
  false, no verdict carries a correction. It is checked by the Report, which receives the option
  as Pydantic validation context (``Report.model_validate(data, context={"suggest_corrections":
  False})``); without context the default (true) applies.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationInfo, model_validator

from inkloom_verify.schemas import (
    MAX_CLAIMS,
    MAX_ERROR_MESSAGE_CHARS,
    ClaimId,
    ClaimText,
    ContentText,
    CorrectionStatus,
    DocumentId,
    ErrorCode,
    EvidencePassage,
    EvidenceStrength,
    PassageText,
    ReferenceSetId,
    ReportStatus,
    RequestId,
    Sha256Hex,
    Verdict,
    VerificationReport,
)
from inkloom_verify.schemas import ClaimResult as InternalResult
from inkloom_verify.schemas import Citation as InternalCitation

PUBLIC_SCHEMA_VERSION = "0.1.0"
SchemaVersion = Literal["0.1.0"]

# Approved fixed map (decision 2). Ordinal, not a probability.
CONFIDENCE: dict[EvidenceStrength, float] = {
    EvidenceStrength.NONE: 0.0,
    EvidenceStrength.WEAK: 0.33,
    EvidenceStrength.MODERATE: 0.67,
    EvidenceStrength.STRONG: 1.0,
}

Offset = Annotated[int, Field(strict=True, ge=0)]


class _Public(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Span(_Public):
    """Half-open [start, end) in Unicode code points. Used for a claim's span in the content and
    for a passage's or quote's location in its reference document."""

    start: Offset
    end: Annotated[int, Field(strict=True)]

    @model_validator(mode="after")
    def _check(self) -> Span:
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start


class Claim(_Public):
    schema_version: SchemaVersion = PUBLIC_SCHEMA_VERSION
    claim_id: ClaimId
    text: ClaimText  # exactly the content at ``span`` (internal contract 0.2.0)
    span: Span

    @model_validator(mode="after")
    def _check(self) -> Claim:
        if len(self.text) != self.span.length:
            raise ValueError("claim text length does not match its span")
        return self


class Passage(_Public):
    schema_version: SchemaVersion = PUBLIC_SCHEMA_VERSION
    doc_id: DocumentId
    location: Span
    text: PassageText
    score: Annotated[float, Field(allow_inf_nan=False)]  # BM25; comparable within one claim only

    @model_validator(mode="after")
    def _check(self) -> Passage:
        if len(self.text) != self.location.length:
            raise ValueError("passage text length does not match its location")
        return self


class Evidence(_Public):
    schema_version: SchemaVersion = PUBLIC_SCHEMA_VERSION
    doc_id: DocumentId
    location: Span
    quote: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _check(self) -> Evidence:
        if len(self.quote) != self.location.length:
            raise ValueError("quote length does not match its location")
        return self


class CorrectionOutcome(str, Enum):
    """The internal CorrectionStatus values, unchanged."""

    PROPOSED = CorrectionStatus.PROPOSED.value
    NEEDS_HUMAN_REVIEW = CorrectionStatus.NEEDS_HUMAN_REVIEW.value  # no safe correction
    FAILED = CorrectionStatus.FAILED.value  # the correction stage could not run


class Correction(_Public):
    """A correction outcome. Only ``proposed`` carries a replacement, and then it must say what it
    replaces (``span`` in the content, ``original_text``) and cite its evidence."""

    status: CorrectionOutcome
    span: Span | None = None
    original_text: ClaimText | None = None
    replacement_text: ClaimText | None = None
    evidence: list[Evidence] = []

    @model_validator(mode="after")
    def _check(self) -> Correction:
        proposed = self.status is CorrectionOutcome.PROPOSED
        parts = (self.span, self.original_text, self.replacement_text)
        if proposed and (any(p is None for p in parts) or not self.evidence):
            raise ValueError("a proposed correction needs span, original_text, replacement_text and evidence")
        if not proposed and (any(p is not None for p in parts) or self.evidence):
            raise ValueError("only a proposed correction carries a replacement or evidence")
        if proposed and len(self.original_text) != self.span.length:  # type: ignore[arg-type,union-attr]
            raise ValueError("original_text length does not match its span")
        return self


class VerdictStatus(str, Enum):
    SUPPORTED = Verdict.SUPPORTED.value
    CONTRADICTED = Verdict.CONTRADICTED.value
    NOT_ENOUGH_EVIDENCE = Verdict.NOT_ENOUGH_EVIDENCE.value
    ERROR = Verdict.ERROR.value


class VerdictResult(_Public):
    """The spec's Verdict (named VerdictResult in Python to keep the internal ``Verdict`` enum)."""

    schema_version: SchemaVersion = PUBLIC_SCHEMA_VERSION
    status: VerdictStatus
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
    evidence: list[Evidence] = []
    correction: Correction | None = None
    needs_human_review: Annotated[bool, Field(strict=True)]
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def _check(self) -> VerdictResult:
        definite = self.status in (VerdictStatus.SUPPORTED, VerdictStatus.CONTRADICTED)
        if definite and not self.evidence:
            raise ValueError(f"{self.status.value} requires at least one evidence item")
        if (self.status is VerdictStatus.ERROR) != (self.error_code is not None):
            raise ValueError("error_code is required for ERROR and only allowed for ERROR")
        if self.status is VerdictStatus.ERROR and self.evidence:
            raise ValueError("an ERROR verdict carries no evidence")
        if self.correction is not None and self.status is not VerdictStatus.CONTRADICTED:
            raise ValueError("only a CONTRADICTED verdict can carry a correction")
        if self.status is not VerdictStatus.SUPPORTED and not self.needs_human_review:
            raise ValueError("every verdict except SUPPORTED needs human review")
        if self.confidence < CONFIDENCE[EvidenceStrength.MODERATE] and not self.needs_human_review:
            # Approved review policy: SUPPORTED on weak evidence (0.33) or less goes to a person.
            raise ValueError("low confidence needs human review")
        if self.correction is not None and self.correction.status is not CorrectionOutcome.PROPOSED and not self.needs_human_review:
            raise ValueError("a contradicted claim without a safe correction needs human review")
        return self


class ReportClaim(_Public):
    """One entry of Report.claims: the claim and its verdict."""

    claim: Claim
    verdict: VerdictResult


class ReportError(_Public):
    """A request-level problem in a report that still has results (Phase 2 decision): for example
    an extraction batch that failed, so some sentences were not checked. Claim-level failures are
    ERROR verdicts instead."""

    code: ErrorCode
    message: Annotated[str, Field(min_length=1, max_length=MAX_ERROR_MESSAGE_CHARS)]


class ReportMetadata(_Public):
    content_hash: Sha256Hex  # lowercase hex SHA-256 of the content, UTF-8
    errors: list[ReportError] = []  # request-level problems; empty when the run had none


class Report(_Public):
    schema_version: SchemaVersion = PUBLIC_SCHEMA_VERSION
    request_id: RequestId
    claims: list[ReportClaim]
    metadata: ReportMetadata

    @model_validator(mode="after")
    def _check(self, info: ValidationInfo) -> Report:
        ids = [c.claim.claim_id for c in self.claims]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate claim_id in claims")
        suggest = True if not info.context else info.context.get("suggest_corrections", True)
        for entry in self.claims:
            verdict = entry.verdict
            if suggest and verdict.status is VerdictStatus.CONTRADICTED and verdict.correction is None:
                raise ValueError(f"{entry.claim.claim_id}: suggest_corrections is true, so a CONTRADICTED verdict needs a correction outcome")
            if not suggest and verdict.correction is not None:
                raise ValueError(f"{entry.claim.claim_id}: suggest_corrections is false, so no correction may be returned")
        return self


# --- Request (POST /v1/verify, Phase 2) ---------------------------------------------------------


class VerifyContent(_Public):
    id: DocumentId
    text: ContentText  # non-blank; at most MAX_CONTENT_CHARS (the endpoint may set a lower limit)


class VerifyOptions(_Public):
    suggest_corrections: StrictBool = True
    max_claims: Annotated[int, Field(strict=True, ge=1, le=MAX_CLAIMS)] = MAX_CLAIMS


class VerifyRequest(_Public):
    """The public request. There is no tenant and no documents: the tenant comes from
    authentication and the documents from the backend's reference-set loader."""

    request_id: RequestId
    content: VerifyContent
    reference_set_id: ReferenceSetId
    options: VerifyOptions = VerifyOptions()


# --- Mapping from the internal contract ----------------------------------------------------------


class NotRepresentable(ValueError):
    """The internal report holds information the public Report has no field for. Raised instead of
    dropping it silently: an empty claim list would read as "nothing to check"."""


def _span(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end}


def _evidence(citation: InternalCitation) -> dict[str, Any]:
    return {"doc_id": citation.doc_id, "location": _span(citation.quote_span.start, citation.quote_span.end), "quote": citation.quote}


def to_public_passage(passage: EvidencePassage) -> Passage:
    return Passage(doc_id=passage.doc_id, location=Span(start=passage.span.start, end=passage.span.end),
                   text=passage.text, score=passage.retrieval.score)


def _verdict(result: InternalResult, suggest_corrections: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": result.verdict.value,
        "confidence": CONFIDENCE[result.evidence_strength],
        "evidence": [_evidence(c) for c in result.citations],
        "needs_human_review": result.requires_human_review,
    }
    if result.error is not None:
        data["error_code"] = result.error.code.value
    if suggest_corrections and result.verdict is Verdict.CONTRADICTED:
        attempt = result.correction_attempt
        if attempt is None:
            raise NotRepresentable(f"{result.claim.claim_id}: suggest_corrections is true but no correction was attempted")
        correction: dict[str, Any] = {"status": attempt.status.value}
        if result.correction is not None:
            c = result.correction
            correction.update(span=_span(c.target_span.start, c.target_span.end), original_text=c.original_text,
                              replacement_text=c.replacement_text, evidence=[_evidence(x) for x in c.citations])
        data["correction"] = correction
    return data


def to_public_report(report: VerificationReport, suggest_corrections: bool = True) -> Report:
    """The public Report for an internal report.

    A FAILED report has no results to show and raises NotRepresentable; the endpoint answers it
    with an error (HTTP 503). Request-level errors of a report that has results go to
    ``metadata.errors``, so successful claims are never discarded. Claim-level failures are ERROR
    verdicts with their error_code, next to every other claim's result.
    """
    if report.status is ReportStatus.FAILED:
        codes = ", ".join(sorted({e.code.value for e in report.errors})) or "none"
        raise NotRepresentable(f"report FAILED ({codes}): there are no results to return")
    claims = [
        {"claim": {"claim_id": r.claim.claim_id, "text": r.claim.text,
                   "span": _span(r.claim.source_span.start, r.claim.source_span.end)},
         "verdict": _verdict(r, suggest_corrections)}
        for r in report.results
    ]
    metadata = {"content_hash": report.content_sha256,
                "errors": [{"code": e.code.value, "message": e.message} for e in report.errors]}
    data = {"request_id": report.request_id, "claims": claims, "metadata": metadata}
    return Report.model_validate(data, context={"suggest_corrections": suggest_corrections})


__all__ = [
    "CONFIDENCE", "PUBLIC_SCHEMA_VERSION", "Claim", "Correction", "CorrectionOutcome", "Evidence", "NotRepresentable",
    "Passage", "Report", "ReportClaim", "ReportError", "ReportMetadata", "Span", "VerdictResult", "VerdictStatus",
    "VerifyContent", "VerifyOptions", "VerifyRequest",
    "to_public_passage", "to_public_report",
]
