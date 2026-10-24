"""Scripted, deterministic evaluations: what the engine's code enforces, whatever a model says.

Nothing here measures model quality. Every model in this module is a script:

* adversaries, which fabricate quotes or assert verdicts regardless of the evidence, run through
  the real retrieval, verifier and citation guard (enforcement);
* fault injection, which makes the provider fail at one stage and checks the engine reports an
  ERROR, a FAILED report or a FAILED correction instead of a verdict (error handling).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from inkloom_verify.evaluation.metrics import Ratio, ratio
from inkloom_verify.evaluation.runner import EngineVerifierPredictor, _eval_claim, evaluate
from inkloom_verify.pipeline import verify_request
from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderNotConfiguredError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from inkloom_verify.providers.fake import ResponderProvider
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.schemas import EvalRecord, ReferenceDocument, VerificationRequest
from inkloom_verify.verification import ClaimVerifier, verify_claim

Responder = Callable[[JsonCompletionRequest], Any]


def data_block(request: JsonCompletionRequest, tag: str) -> dict:
    return json.loads(request.user.split(f"<{tag}>\n", 1)[1].rsplit(f"\n</{tag}>", 1)[0])


def first_words(text: str, n: int = 8) -> str:
    end = 0
    for word in text.split()[:n]:
        end = text.index(word, end) + len(word)
    return text[:end]


# --- Adversaries -------------------------------------------------------------------------------


def fabricator(request: JsonCompletionRequest) -> dict:
    """SUPPORTED, 'quoting' the claim itself whatever the passages say."""
    block = data_block(request, "verification_input_json")
    return {
        "verdict": "SUPPORTED",
        "citations": [{"passage": "P1", "quote": block["claim"]}],
        "rationale": "x",
    }


def valid_quote_always_supported(request: JsonCompletionRequest) -> dict:
    """Quotes real passage text verbatim, then asserts SUPPORTED regardless of meaning."""
    block = data_block(request, "verification_input_json")
    return {
        "verdict": "SUPPORTED",
        "citations": [{"passage": "P1", "quote": first_words(block["passages"][0]["text"])}],
        "rationale": "x",
    }


def valid_quote_always_contradicted(request: JsonCompletionRequest) -> dict:
    block = data_block(request, "verification_input_json")
    return {
        "verdict": "CONTRADICTED",
        "citations": [{"passage": "P1", "quote": first_words(block["passages"][0]["text"])}],
        "rationale": "x",
    }


ADVERSARIES: dict[str, Responder] = {
    "fabricator": fabricator,
    "valid_quote_always_supported": valid_quote_always_supported,
    "valid_quote_always_contradicted": valid_quote_always_contradicted,
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EnforcementResult(_Model):
    adversary: str
    definite_answers: int  # claims where the model answered SUPPORTED/CONTRADICTED
    accepted: int  # answers that survived the citation guard and support checks
    downgrade_reasons: dict[str, int]
    accepted_citations: int
    accepted_citations_verbatim: int  # accepted citations whose quote is exactly the source text
    accepted_quotes_not_in_any_source: int  # fabrications that got through: must be 0
    citation_validity: Ratio  # harness definition (EVAL.md)
    false_supported: Ratio  # harness definition (EVAL.md)


def enforcement(
    records: Sequence[EvalRecord], name: str, adversary: Responder
) -> EnforcementResult:
    definite = accepted = cited = verbatim = fabricated = 0
    reasons: Counter[str] = Counter()
    for record in records:
        verifier = ClaimVerifier(ResponderProvider(adversary), record.references)
        result = verify_claim(_eval_claim(record), BM25Retriever(record.references), verifier)
        if result.citation_guard is None:
            continue  # no passages were retrieved, so no model call was made
        definite += result.citation_guard.model_verdict.value != "NOT_ENOUGH_EVIDENCE"
        if result.citation_guard.downgraded:
            reasons.update(r.reason.value for r in result.citation_guard.rejected)
        elif result.citations:
            accepted += 1
        documents = {d.doc_id: d for d in record.references}
        for citation in result.citations:
            cited += 1
            verbatim += citation.matches(documents[citation.doc_id])
            fabricated += not any(citation.quote in d.text for d in documents.values())
    predictor = EngineVerifierPredictor(ResponderProvider(adversary))
    results = evaluate(
        records, {r.record_id: predictor.predict(r) for r in records}, retrieval=None
    )
    return EnforcementResult(
        adversary=name,
        definite_answers=definite,
        accepted=accepted,
        downgrade_reasons=dict(sorted(reasons.items())),
        accepted_citations=cited,
        accepted_citations_verbatim=verbatim,
        accepted_quotes_not_in_any_source=fabricated,
        citation_validity=results.citations.validity,
        false_supported=results.verdict.false_supported_rate,
    )


# --- Fault injection ---------------------------------------------------------------------------

FAULTS: dict[str, Callable[[], Any]] = {
    "timeout": lambda: ProviderTimeoutError("scripted timeout"),
    "rate_limit": lambda: ProviderRateLimitError("scripted 429"),
    "unavailable": lambda: ProviderUnavailableError("scripted 503"),
    "malformed_json": lambda: MalformedOutputError("scripted: reply is not valid JSON"),
    "schema_invalid": lambda: {"unexpected": "shape"},
    "not_configured": lambda: ProviderNotConfiguredError("scripted: provider not configured"),
}
STAGE_SCHEMAS = {
    "extraction": "claim_extraction",
    "verification": "claim_verification",
    "correction": "claim_correction",
}


class FaultCase(_Model):
    name: str
    stage: Literal["extraction", "verification", "correction"]
    fault: str
    expect_report_status: Literal["COMPLETED", "PARTIAL", "FAILED"]
    expect_error_code: str
    expect_claim_verdict: Literal["CONTRADICTED", "ERROR"] | None = None
    expect_correction_status: Literal["failed"] | None = None


class FaultOutcome(_Model):
    name: str
    passed: bool
    observed: dict[str, Any]


def _cooperative(request: JsonCompletionRequest) -> dict:
    """A scripted model that reaches every stage: one factual claim per sentence, a CONTRADICTED
    verdict quoting the top passage (so a correction is attempted), and a correction it declines."""
    if request.schema_name == "claim_extraction":
        return {
            "statements": [
                {
                    "sentence_id": s["id"],
                    "kind": "factual",
                    "claims": [{"text": s["text"], "source_quote": s["text"]}],
                }
                for s in data_block(request, "content_json")["sentences"]
            ]
        }
    if request.schema_name == "claim_verification":
        return valid_quote_always_contradicted(request)
    return {
        "status": "needs_human_review",
        "original_text": "",
        "replacement_text": "",
        "citations": [],
        "reason": "x",
    }


FAULT_CLAIM = "Lumen Pods offer up to 12 hours of playback per charge."


def fault_request(document: ReferenceDocument, claim: str = FAULT_CLAIM) -> VerificationRequest:
    """One claim against one document: enough to reach every stage once."""
    return VerificationRequest(
        request_id="req-fault",
        tenant_id="tenant-eval",
        content={"text": claim},
        references=[document],
    )


def run_fault_case(case: FaultCase, request: VerificationRequest) -> FaultOutcome:
    target = STAGE_SCHEMAS[case.stage]
    fault = FAULTS[case.fault]

    def respond(call: JsonCompletionRequest):
        return fault() if call.schema_name == target else _cooperative(call)

    report = verify_request(request, ResponderProvider(respond))
    result = report.results[0] if report.results else None
    observed: dict[str, Any] = {
        "report_status": report.status.value,
        "claim_verdict": result.verdict.value if result else None,
    }
    codes = [e.code.value for e in report.errors]
    if result is not None and result.error is not None:
        codes.append(result.error.code.value)
    if result is not None and result.correction_attempt is not None:
        observed["correction_status"] = result.correction_attempt.status.value
        if result.correction_attempt.error is not None:
            codes.append(result.correction_attempt.error.code.value)
    observed["error_codes"] = codes
    passed = (
        observed["report_status"] == case.expect_report_status
        and case.expect_error_code in codes
        and (
            case.expect_claim_verdict is None
            or observed["claim_verdict"] == case.expect_claim_verdict
        )
        and (
            case.expect_correction_status is None
            or observed.get("correction_status") == case.expect_correction_status
        )
    )
    return FaultOutcome(name=case.name, passed=passed, observed=observed)


def load_fault_cases(path: Path) -> list[FaultCase]:
    return [FaultCase.model_validate(c) for c in json.loads(path.read_text(encoding="utf-8"))]


def fault_pass_rate(outcomes: Sequence[FaultOutcome]) -> Ratio:
    return ratio(sum(o.passed for o in outcomes), len(outcomes))


# --- Full-pipeline safety (EVAL.md Phase 6) ---------------------------------------------------------


class _PipelineAdversary:
    """Drives the full pipeline: every sentence is one claim, verification answers with the
    adversary, corrections are declined."""

    name = "scripted-adversary"

    def __init__(self, adversary: Responder) -> None:
        self.adversary = adversary

    def sampling(self) -> dict[str, Any]:
        return {}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        if request.schema_name == "claim_extraction":
            data = {
                "statements": [
                    {
                        "sentence_id": s["id"],
                        "kind": "factual",
                        "claims": [{"text": s["text"], "source_quote": s["text"]}],
                    }
                    for s in data_block(request, "content_json")["sentences"]
                ]
            }
        elif request.schema_name == "claim_verification":
            data = self.adversary(request)
        else:
            data = {
                "status": "needs_human_review",
                "original_text": "",
                "replacement_text": "",
                "citations": [],
                "reason": "Scripted adversary.",
            }
        return JsonCompletion(data=data, model="scripted/adversary", attempts=1)


def pipeline_safety(records: Sequence[EvalRecord], adversary: Responder) -> dict[str, Any]:
    """The adversary through ``verify_request`` (guard, support checks, decision policy) on every
    record. Not model quality: it measures what the code lets through. The key number is
    ``auto_cleared_not_supported``: records not labelled SUPPORTED that no person would review."""
    from inkloom_verify.evaluation import required_metrics
    from inkloom_verify.evaluation.pipeline_predictor import PipelinePredictor

    predictor = PipelinePredictor(_PipelineAdversary(adversary))
    predictions = {r.record_id: predictor.predict(r) for r in records}
    m = required_metrics.compute(records, predictions, predictor.outcomes)
    cleared = m.review["auto_cleared_but_not_supported"]
    return {
        "records": len(records),
        "predicted": dict(sorted(Counter(p.verdict.value for p in predictions.values()).items())),
        "auto_cleared_not_supported": len(cleared),
        "auto_cleared_not_supported_records": cleared,
        "citation_resolution": m.citation_resolution.value if m.citation_resolution else None,
        "citations": m.citation_failures["citations"],
        "human_review_share": m.human_review_share.value if m.human_review_share else None,
    }
