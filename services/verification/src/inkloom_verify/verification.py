"""Claim verification: one claim and its retrieved passages in, one ClaimResult out.

The verifier sees exactly a ``ClaimVerificationInput``: the claim and at most eight passages,
each shown to the model as a label and its text. Never the corpus, never other claims.

Outcomes:

* no passages retrieved -> NOT_ENOUGH_EVIDENCE without calling the model;
* passage provenance does not check out -> ERROR (a processing failure, not a verdict);
* provider failure, or output still invalid after one repair -> ERROR;
* model answers NOT_ENOUGH_EVIDENCE -> NOT_ENOUGH_EVIDENCE, any citations discarded;
* model answers SUPPORTED/CONTRADICTED -> kept only if it cites at least once and every
  citation passes the citation guard; otherwise downgraded to NOT_ENOUGH_EVIDENCE.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify.citation_guard import CitationGuard
from inkloom_verify.extraction import describe_validation_error
from inkloom_verify.prompts import verification as prompt
from inkloom_verify.providers.base import JsonCompletionRequest, LLMProvider, MalformedOutputError, ProviderError
from inkloom_verify.retrieval import EvidenceRetriever
from inkloom_verify.schemas import (
    MAX_RATIONALE_CHARS,
    Citation,
    CitationGuardReport,
    Claim,
    ClaimResult,
    ClaimVerificationInput,
    ErrorCode,
    EvidencePassage,
    PipelineStage,
    ProcessingError,
    ReferenceDocument,
    RejectedCitation,
    Verdict,
    GuardRejectionReason,
)

logger = logging.getLogger(__name__)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ModelCitation(_Strict):
    passage: str
    quote: str


class _ModelOutput(_Strict):
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"]
    citations: list[_ModelCitation] = Field(max_length=20)
    rationale: str


class VerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_output_tokens: int = Field(default=1_500, ge=256, le=8_000)


class ClaimVerifier:
    """Verifies claims against passages drawn from one request's reference documents."""

    def __init__(
        self,
        provider: LLMProvider,
        documents: Sequence[ReferenceDocument],
        config: VerificationConfig | None = None,
    ) -> None:
        self.provider = provider
        self.documents = list(documents)
        self.config = config or VerificationConfig()
        self.models_used: set[str] = set()

    def verify(self, verifier_input: ClaimVerificationInput) -> ClaimResult:
        claim, passages = verifier_input.claim, list(verifier_input.passages)
        guard = CitationGuard(self.documents, passages)
        if guard.invalid_passages:
            return self._error(
                claim,
                passages,
                ProcessingError(
                    code=ErrorCode.INTERNAL_ERROR,
                    stage=PipelineStage.CITATION_VALIDATION,
                    message="Retrieved evidence does not match the request's reference documents.",
                    retryable=False,
                    claim_id=claim.claim_id,
                ),
            )

        labels = {f"P{i}": p.passage_id for i, p in enumerate(passages, start=1)}
        request = JsonCompletionRequest(
            system=prompt.SYSTEM_PROMPT,
            user=prompt.user_message(claim.text, [(label, guard.passages[pid].text) for label, pid in labels.items()]),
            schema_name="claim_verification",
            json_schema=prompt.OUTPUT_SCHEMA,
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            output = self._ask(request)
        except ProviderError as error:
            return self._error(claim, passages, error.to_processing_error(PipelineStage.VERIFICATION, claim.claim_id))

        model_verdict = Verdict(output.verdict)
        rationale = output.rationale.strip()[:MAX_RATIONALE_CHARS] or None
        if model_verdict is Verdict.NOT_ENOUGH_EVIDENCE:
            return ClaimResult(
                claim=claim,
                verdict=Verdict.NOT_ENOUGH_EVIDENCE,
                evidence=passages,
                model_rationale=rationale,
                citation_guard=CitationGuardReport(model_verdict=model_verdict, downgraded=False),
            )

        citations: list[Citation] = []
        rejected: list[RejectedCitation] = []
        seen: set[tuple[str, int, int]] = set()
        for cited in output.citations:
            label = cited.passage.strip()
            checked = guard.check(labels.get(label), cited.quote)
            if isinstance(checked, GuardRejectionReason):
                rejected.append(RejectedCitation(reason=checked, passage_id=labels.get(label), cited_as=label[:64] or None))
                continue
            key = (checked.passage_id, checked.quote_span.start, checked.quote_span.end)
            if key not in seen:
                seen.add(key)
                citations.append(checked)
        if not output.citations:
            rejected.append(RejectedCitation(reason=GuardRejectionReason.NO_CITATION))

        if rejected:
            logger.info(
                "verification claim=%s model_verdict=%s downgraded reasons=%s",
                claim.claim_id, model_verdict.value, ",".join(sorted({r.reason.value for r in rejected})),
            )
            return ClaimResult(
                claim=claim,
                verdict=Verdict.NOT_ENOUGH_EVIDENCE,
                evidence=passages,
                model_rationale=rationale,
                citation_guard=CitationGuardReport(model_verdict=model_verdict, downgraded=True, rejected=rejected),
            )
        logger.info("verification claim=%s verdict=%s citations=%d", claim.claim_id, model_verdict.value, len(citations))
        return ClaimResult(
            claim=claim,
            verdict=model_verdict,
            evidence=passages,
            citations=citations,
            model_rationale=rationale,
            citation_guard=CitationGuardReport(model_verdict=model_verdict, downgraded=False),
        )

    def _ask(self, request: JsonCompletionRequest) -> _ModelOutput:
        """One call, and one repair call listing the problems if the reply does not fit the schema."""
        completion = self.provider.complete_json(request)
        self.models_used.add(completion.model)
        try:
            return _ModelOutput.model_validate(completion.data)
        except ValidationError as error:
            problems = describe_validation_error(error)
        repaired = self.provider.complete_json(
            request.model_copy(update={"user": prompt.repair_message(request.user, problems)})
        )
        self.models_used.add(repaired.model)
        try:
            return _ModelOutput.model_validate(repaired.data)
        except ValidationError:
            raise MalformedOutputError("Verification output did not match the schema after one repair attempt.") from None

    @staticmethod
    def _error(claim: Claim, passages: list[EvidencePassage], error: ProcessingError) -> ClaimResult:
        logger.warning("verification claim=%s error=%s", claim.claim_id, error.code.value)
        return ClaimResult(claim=claim, verdict=Verdict.ERROR, evidence=passages, error=error)


def verify_claim(
    claim: Claim, retriever: EvidenceRetriever, verifier: ClaimVerifier, top_k: int | None = None
) -> ClaimResult:
    """Retrieves evidence for one claim and verifies it. No passages means no model call."""
    passages = retriever.retrieve(claim, top_k=top_k)
    if not passages:
        return ClaimResult(claim=claim, verdict=Verdict.NOT_ENOUGH_EVIDENCE, evidence=[])
    return verifier.verify(ClaimVerificationInput(claim=claim, passages=passages))
