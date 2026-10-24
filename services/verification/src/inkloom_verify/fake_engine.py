"""The walking-skeleton engine: real retrieval, canned verdicts. Development and integration only.

THE VERDICTS ARE NOT VERIFICATION. Evidence is retrieved for real (BM25 over the request's own
reference set, as in the pipeline), but no model is called: verdicts are assigned by claim
position, not by evidence. It exists so the endpoint, the contracts and the frontend can be
wired up before the real verifier is behind the endpoint (Phase 4).

Every report it produces says so, in three places a consumer cannot miss:

* ``provenance.provider == "fake"`` and ``provenance.model_id == "fake/canned-v1"``;
* a request-level ``PROVIDER_NOT_CONFIGURED`` error stating no AI verification was performed,
  which also makes the status PARTIAL (or FAILED) and ``score.requires_human_review`` true, so a
  canned SUPPORTED can never read as a clean, review-free result;
* every result's ``model_rationale`` starts with ``FAKE ENGINE``.

The endpoint also sends ``X-Inkloom-Engine-Mode: fake``.
"""

from __future__ import annotations

from inkloom_verify import __version__
from inkloom_verify.chunking import sentence_spans
from inkloom_verify.schemas import (
    MAX_CLAIM_CHARS,
    MAX_CLAIMS,
    Citation,
    Claim,
    ClaimResult,
    EngineProvenance,
    ErrorCode,
    EvidencePassage,
    PipelineStage,
    ProcessingError,
    ReportScore,
    ReportStatus,
    RetrievalMethod,
    SourceSpan,
    Verdict,
    VerificationReport,
    VerificationRequest,
)
from inkloom_verify.retrieval import BM25Retriever
from inkloom_verify.scope import check_report_scope

FAKE_NOTICE = "FAKE ENGINE: canned development result; no AI verification was performed."
FAKE_MODEL_ID = "fake/canned-v1"
# Verdicts are handed out in this order, by claim position, so every shape can be rendered.
CANNED_VERDICTS = (
    Verdict.SUPPORTED,
    Verdict.CONTRADICTED,
    Verdict.NOT_ENOUGH_EVIDENCE,
    Verdict.ERROR,
)
QUOTE_WORDS = 8


def _opening_words(passage: EvidencePassage) -> Citation | None:
    """A verbatim citation of the passage's first few words, or None if it has fewer than two."""
    words = passage.text.split()
    if len(words) < 2:
        return None
    end = 0
    for word in words[:QUOTE_WORDS]:
        end = passage.text.index(word, end) + len(word)
    return Citation(
        doc_id=passage.doc_id,
        doc_text_sha256=passage.doc_text_sha256,
        passage_id=passage.passage_id,
        quote=passage.text[:end],
        quote_span=SourceSpan(start=passage.span.start, end=passage.span.start + end),
    )


class CannedVerifier:
    """Assigns canned verdicts by claim position. Replaced by the real verifier in Phase 4."""

    def verify(self, claim: Claim, passages: list[EvidencePassage], position: int) -> ClaimResult:
        verdict = CANNED_VERDICTS[position % len(CANNED_VERDICTS)]
        citation = _opening_words(passages[0]) if passages else None
        if verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED) and citation is None:
            verdict = Verdict.NOT_ENOUGH_EVIDENCE  # never a factual verdict without a quote
        if verdict is Verdict.ERROR:
            return ClaimResult(
                claim=claim,
                verdict=verdict,
                evidence=passages,
                error=ProcessingError(
                    code=ErrorCode.INTERNAL_ERROR,
                    stage=PipelineStage.VERIFICATION,
                    message="FAKE ENGINE: canned ERROR result for development.",
                    retryable=False,
                    claim_id=claim.claim_id,
                ),
            )
        return ClaimResult(
            claim=claim,
            verdict=verdict,
            evidence=passages,
            citations=[citation] if verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED) else [],
            model_rationale=FAKE_NOTICE,
        )


class FakeEngine:
    """Implements the VerificationEngine protocol with canned results. Development only."""

    mode = "fake"

    def verify(
        self,
        request: VerificationRequest,
        *,
        suggest_corrections: bool = True,
        max_claims: int | None = None,
    ) -> VerificationReport:
        """Canned results; ``suggest_corrections`` is ignored (the fake engine never corrects)."""
        text = request.content.text
        spans = [
            s
            for s in sentence_spans(text, MAX_CLAIM_CHARS)
            if any(c.isalnum() for c in s.slice(text))
        ]
        claims = [
            Claim(claim_id=f"clm_{i:04d}", text=span.slice(text), source_span=span)
            for i, span in enumerate(spans[: max_claims or MAX_CLAIMS], start=1)
        ]
        retriever = BM25Retriever.for_request(request)
        verifier = CannedVerifier()
        results = [
            verifier.verify(claim, retriever.retrieve(claim), i) for i, claim in enumerate(claims)
        ]
        notice = ProcessingError(
            code=ErrorCode.PROVIDER_NOT_CONFIGURED,
            stage=PipelineStage.REQUEST,
            message="Fake engine: canned results for development; no AI verification was performed.",
            retryable=False,
        )
        report = VerificationReport(
            request_id=request.request_id,
            tenant_id=request.tenant_id,
            reference_set_id=request.reference_set_id,
            content_sha256=request.content.text_sha256,
            content_length=len(text),
            references=[d.descriptor() for d in request.references],
            status=ReportStatus.PARTIAL if results else ReportStatus.FAILED,
            results=results,
            errors=[notice],
            provenance=EngineProvenance(
                engine_version=__version__,
                retrieval_method=RetrievalMethod.BM25,
                provider="fake",
                model_id=FAKE_MODEL_ID,
            ),
            score=ReportScore.compute(results, [notice]),
        )
        check_report_scope(request, report)
        return report
