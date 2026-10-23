"""Evaluates the engine's real end-to-end pipeline, ``inkloom_verify.pipeline.verify_request``,
on each ``EvalRecord``: the same function ``POST /v1/verify`` calls.

For each record the claim text is submitted as the content and the record's references as the
reference set. The pipeline then runs as in production: claim extraction, BM25 retrieval,
verification, the citation guard and support checks, correction of CONTRADICTED claims (with its
re-check), and the human-review decision. Nothing here classifies anything: this module only
submits the request and reads the report.

**One record, several claims.** Extraction may split one record's text into several claims (a
compound claim, or a claim plus an injected sentence). The record's predicted verdict is then the
*most severe* of its claims' verdicts: CONTRADICTED, then ERROR, then NOT_ENOUGH_EVIDENCE, then
SUPPORTED. One wrong part makes the record contradicted, and a record is SUPPORTED only if every
claim is, the same rule the labels follow (EVAL.md "Labelling policy"). The prediction's
citations are those of the claims that have that verdict. Every claim, with all its evidence,
citations and correction, is kept in the per-case outcome.

**Records the pipeline did not check.** If extraction finds no claim, or the whole run fails,
the record is predicted ERROR (counted in the error rate) and its outcome says why
(``skipped``: ``no_claim_extracted``; ``error``: the report's error codes). It is never dropped.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from inkloom_verify.evaluation.runner import EvalPrediction, PredictedCitation, PredictedSpan
from inkloom_verify.pipeline import PipelineConfig, verify_request
from inkloom_verify.providers.base import LLMProvider
from inkloom_verify.schemas import ClaimResult, EvalRecord, ReportStatus, Verdict, VerificationRequest

SEVERITY = [Verdict.CONTRADICTED, Verdict.ERROR, Verdict.NOT_ENOUGH_EVIDENCE, Verdict.SUPPORTED]
EVAL_TENANT = "tenant-eval"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseCitation(_Model):
    doc_id: str
    passage_id: str
    quote: str
    start: int
    end: int


class CaseEvidence(_Model):
    passage_id: str
    doc_id: str
    start: int
    end: int
    rank: int | None = None


class CaseCorrection(_Model):
    status: str
    original_text: str | None = None
    replacement_text: str | None = None
    citations: list[CaseCitation] = []  # the evidence the proposal cites (for traceability)
    issues: list[str] = []
    recheck_verdict: str | None = None
    error_code: str | None = None


class CaseClaim(_Model):
    claim_id: str
    text: str
    statement: str | None = None  # the claim as checked (the standalone rewording); None in older case files
    start: int
    end: int
    verdict: str
    evidence_strength: str
    requires_human_review: bool
    review_reasons: list[str] = []
    evidence: list[CaseEvidence]
    citations: list[CaseCitation]
    guard_rejections: list[str]
    correction: CaseCorrection | None = None
    error_code: str | None = None


class CaseOutcome(_Model):
    """Everything the pipeline produced for one record, for debugging. No secrets, no prompts."""

    record_id: str
    split: str
    expected: str
    predicted: str
    outcome: Literal["correct", "incorrect", "error", "skipped"]
    reason: str | None = None
    report_status: str
    report_errors: list[dict[str, Any]]
    requires_human_review: bool
    claims: list[CaseClaim]
    prompt_versions: dict[str, str]
    models: list[str]
    seconds: float


def aggregate(verdicts: list[Verdict]) -> Verdict:
    """The record's verdict: the most severe claim verdict (see the module docstring)."""
    return min(verdicts, key=SEVERITY.index)


def _claim(result: ClaimResult) -> CaseClaim:
    attempt = result.correction_attempt
    correction = None
    if attempt is not None:
        correction = CaseCorrection(
            status=attempt.status.value,
            original_text=result.correction.original_text if result.correction else None,
            replacement_text=result.correction.replacement_text if result.correction else None,
            citations=[CaseCitation(doc_id=c.doc_id, passage_id=c.passage_id, quote=c.quote, start=c.quote_span.start,
                                    end=c.quote_span.end) for c in result.correction.citations] if result.correction else [],
            issues=[i.code.value for i in attempt.issues],
            recheck_verdict=attempt.recheck_verdict.value if attempt.recheck_verdict else None,
            error_code=attempt.error.code.value if attempt.error else None,
        )
    return CaseClaim(
        claim_id=result.claim.claim_id, text=result.claim.text, statement=result.claim.statement,
        start=result.claim.source_span.start, end=result.claim.source_span.end,
        verdict=result.verdict.value, evidence_strength=result.evidence_strength.value,
        requires_human_review=result.requires_human_review,
        review_reasons=[r.value for r in result.review_reasons],
        evidence=[CaseEvidence(passage_id=p.passage_id, doc_id=p.doc_id, start=p.span.start, end=p.span.end,
                               rank=p.retrieval.rank) for p in result.evidence],
        citations=[CaseCitation(doc_id=c.doc_id, passage_id=c.passage_id, quote=c.quote,
                                start=c.quote_span.start, end=c.quote_span.end) for c in result.citations],
        guard_rejections=[r.reason.value for r in result.citation_guard.rejected] if result.citation_guard else [],
        correction=correction,
        error_code=result.error.code.value if result.error else None,
    )


class PipelinePredictor:
    """``Predictor`` for the evaluation runner: one ``verify_request`` call per record."""

    def __init__(self, provider: LLMProvider, config: PipelineConfig | None = None) -> None:
        self.provider = provider
        self.config = config or PipelineConfig()
        self.name = f"engine/full-pipeline/{provider.name}"
        self.models: set[str] = set()
        self.outcomes: dict[str, CaseOutcome] = {}

    def predict(self, record: EvalRecord) -> EvalPrediction:
        started = time.monotonic()
        request = VerificationRequest(request_id=f"eval-{record.record_id}", tenant_id=EVAL_TENANT,
                                      content={"text": record.claim_text}, references=record.references)
        try:
            report = verify_request(request, self.provider, self.config)
        except Exception as error:  # noqa: BLE001 - verify_request never raises; if it did, the case still counts
            return self._record(record, Verdict.ERROR, [], "error", f"pipeline raised {type(error).__name__}",
                                "FAILED", [], {}, [], started)
        claims = [_claim(r) for r in report.results]
        errors = [{"code": e.code.value, "stage": e.stage.value, "retryable": e.retryable} for e in report.errors]
        prompts = dict(report.provenance.prompt_versions)
        models = sorted(m for m in (report.provenance.model_id or "").split(",") if m)
        if not report.results:
            if report.status is ReportStatus.FAILED or errors:
                reason = "pipeline failed: " + ",".join(sorted({e["code"] for e in errors})) if errors else "pipeline failed"
                return self._record(record, Verdict.ERROR, [], "error", reason, report.status.value, errors, prompts, models, started)
            return self._record(record, Verdict.ERROR, [], "skipped", "no_claim_extracted", report.status.value, errors,
                                prompts, models, started)
        verdict = aggregate([r.verdict for r in report.results])
        citations = [c for r in report.results if r.verdict is verdict for c in r.citations] \
            if verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED) else []
        prediction = EvalPrediction(
            record_id=record.record_id, verdict=verdict,
            citations=[PredictedCitation(doc_id=c.doc_id, quote=c.quote, doc_text_sha256=c.doc_text_sha256,
                                         passage_id=c.passage_id,
                                         quote_span=PredictedSpan(start=c.quote_span.start, end=c.quote_span.end))
                       for c in citations],
            model_id=",".join(models) or None,
            prompt_version=prompts.get("verify_claim"),
        )
        if verdict is Verdict.ERROR:
            codes = sorted({c.error_code for c in claims if c.error_code})
            outcome, reason = "error", "claim error: " + ",".join(codes)
        else:
            outcome, reason = ("correct" if verdict is record.expected_verdict else "incorrect"), None
        self._store(record, prediction.verdict, outcome, reason, report.status.value, errors, claims, prompts, models, started)
        return prediction

    def _record(self, record, verdict, claims, outcome, reason, status, errors, prompts, models, started) -> EvalPrediction:
        self._store(record, verdict, outcome, reason, status, errors, claims, prompts, models, started)
        return EvalPrediction(record_id=record.record_id, verdict=verdict)

    def _store(self, record, verdict, outcome, reason, status, errors, claims, prompts, models, started) -> None:
        self.models |= set(models)
        self.outcomes[record.record_id] = CaseOutcome(
            record_id=record.record_id, split=record.split.value, expected=record.expected_verdict.value,
            predicted=verdict.value, outcome=outcome, reason=reason, report_status=status, report_errors=errors,
            # A record the pipeline could not decide always needs a person.
            requires_human_review=any(c.requires_human_review for c in claims) or not claims,
            claims=claims, prompt_versions=prompts, models=models, seconds=round(time.monotonic() - started, 3),
        )


def decision_policy(config: PipelineConfig) -> dict[str, Any]:
    """The rules and thresholds that decide verdicts and review routing, as used in this run."""
    from inkloom_verify import decision_policy as policy
    from inkloom_verify.citation_guard import CONFLICT_TOPIC_OVERLAP, MIN_QUOTE_WORDS
    from inkloom_verify.security import PROMPT_ECHO_CHARS

    return {
        "policy": policy.describe(config.decision_policy),
        "review_rule": "requires_human_review = any review reason: the fixed floor (verdict != SUPPORTED, or weak "
                       "evidence) plus the policy's additions for SUPPORTED claims (decision_policy.review_reasons)",
        "evidence_strength_rule": "schemas.evidence_strength: none / weak / moderate / strong from citation rank and count",
        "record_verdict_rule": "most severe claim verdict: CONTRADICTED > ERROR > NOT_ENOUGH_EVIDENCE > SUPPORTED",
        "conflict_topic_overlap": CONFLICT_TOPIC_OVERLAP,
        "min_quote_words": MIN_QUOTE_WORDS,
        "prompt_echo_chars": PROMPT_ECHO_CHARS,
        "correct_contradicted": config.correct_contradicted,
        "max_repairs": {"extraction": config.extraction.max_repairs, "verification": config.verification.max_repairs,
                        "correction": config.correction.max_repairs},
        "budget": config.budget.model_dump(mode="json"),
    }


def retrieval_parameters(config: PipelineConfig) -> dict[str, Any]:
    return {"chunking": config.chunking.model_dump(mode="json"), "retrieval": config.retrieval.model_dump(mode="json")}
