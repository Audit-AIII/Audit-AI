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

from inkloom_verify.citation_guard import CitationGuard, conflicting_passage, support_problems
from inkloom_verify.extraction import describe_validation_error
from inkloom_verify.prompts import verification as prompt
from inkloom_verify.prompts.loader import load_prompt
from inkloom_verify.providers.base import JsonCompletionRequest, LLMProvider, MalformedOutputError, ProviderError
from inkloom_verify.retrieval import EvidenceRetriever
from inkloom_verify.security import clean_display_text, instruction_like, model_text_for_display
from inkloom_verify.schemas import (
    MAX_PASSAGE_CHARS,
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
    passage: str = Field(max_length=32)
    quote: str = Field(max_length=MAX_PASSAGE_CHARS)


class _ModelOutput(_Strict):
    verdict: Literal["SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE"]
    citations: list[_ModelCitation] = Field(max_length=20)
    rationale: str = Field(max_length=8_000)


class VerificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_output_tokens: int = Field(default=1_500, ge=256, le=8_000)
    # Repair calls after a reply that does not match the schema, before MALFORMED_MODEL_OUTPUT
    # (HTTP 422 UNPARSEABLE_MODEL_OUTPUT when no claim could be checked). Transient provider
    # failures are retried by the provider adapter itself (INKLOOM_LLM_MAX_RETRIES).
    max_repairs: int = Field(default=1, ge=0, le=3)
    # The prompt file to load (prompts/<version>.txt). An exact version, never "latest".
    prompt_version: str = prompt.PROMPT_VERSION


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
        self.prompt = load_prompt("verification", self.config.prompt_version)  # fails clearly if missing
        self.prompt_sent = False
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
            system=self.prompt.text,
            user=prompt.user_message(claim.statement, [(label, guard.passages[pid].text) for label, pid in labels.items()]),
            schema_name="claim_verification",
            json_schema=prompt.OUTPUT_SCHEMA,
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            output = self._ask(request)
        except ProviderError as error:
            return self._error(claim, passages, error.to_processing_error(PipelineStage.VERIFICATION, claim.claim_id))

        model_verdict = Verdict(output.verdict)
        rationale = model_text_for_display(output.rationale, MAX_RATIONALE_CHARS, self.prompt.text)
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
                rejected.append(RejectedCitation(reason=checked, passage_id=labels.get(label), cited_as=clean_display_text(label, 64)))
                continue
            key = (checked.passage_id, checked.quote_span.start, checked.quote_span.end)
            if key not in seen:
                seen.add(key)
                citations.append(checked)
        if not output.citations:
            rejected.append(RejectedCitation(reason=GuardRejectionReason.NO_CITATION))
        if model_verdict is Verdict.SUPPORTED and citations and not rejected:
            # Valid quotes are necessary, not sufficient: they must also carry the claim's figures,
            # and its names must be in the cited passages.
            cited_passages = [guard.passages[pid].text for pid in dict.fromkeys(c.passage_id for c in citations)]
            rejected.extend(
                RejectedCitation(reason=r)
                for r in support_problems(claim.statement, [c.quote for c in citations], cited_passages)
            )
            # A claim that gives instructions is checked, never confirmed: dropping it would let a
            # false claim go unchecked by adding "ignore the evidence" to its sentence, and
            # confirming it would publish the instruction as verified (PROMPTS.md Phase 6).
            if instruction_like(claim.text) or instruction_like(claim.statement):
                rejected.append(RejectedCitation(reason=GuardRejectionReason.INSTRUCTION_TEXT))
        if citations and not rejected:
            # References that disagree about the claim's figure: no verdict, a person decides.
            other = conflicting_passage(claim.statement, passages)
            if other is not None:
                rejected.append(RejectedCitation(reason=GuardRejectionReason.CONFLICTING_EVIDENCE, passage_id=other.passage_id))

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
        """One call, then up to ``max_repairs`` repair calls listing the problems (never the reply)
        while the reply does not fit the schema."""
        self.prompt_sent = True
        current = request
        for attempt in range(self.config.max_repairs + 1):
            completion = self.provider.complete_json(current)
            self.models_used.add(completion.model)
            try:
                return _ModelOutput.model_validate(completion.data)
            except ValidationError as error:
                problems = describe_validation_error(error)
            current = request.model_copy(update={"user": prompt.repair_message(request.user, problems)})
        raise MalformedOutputError(
            f"Verification output did not match the schema after {self.config.max_repairs} repair attempt(s)."
        )

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
