"""Data contracts for the INKLOOM claim-verification engine.

Every structure that crosses a boundary of the engine (caller -> engine, engine -> verifier,
engine -> caller, evaluation data -> harness) is defined here, and only here.

Conventions that hold for every model in this module:

* Offsets are half-open ``[start, end)`` indexes into a Python ``str``, i.e. Unicode code
  points. They are NOT UTF-8 byte offsets and NOT UTF-16 code units (JavaScript string
  indexes). See CONTRACTS.md, "Offsets".
* Text is never stripped or normalised on input. Offsets are only meaningful against the exact
  text they were computed from, and the ``*_sha256`` fields pin that text.
* Unknown fields are rejected (``extra="forbid"``) and models are immutable (``frozen=True``).
* Model-generated prose (``model_rationale``) is carried for display only. It is never evidence
  and no rule in this module accepts it in place of a citation.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ContractVersion = Literal["0.1.0"]
CONTRACT_VERSION: ContractVersion = "0.1.0"

# Provisional limits. They bound cost and memory per request and are expected to be tuned once
# real documents are available; changing them is a contract change (see CONTRACTS.md).
MAX_CONTENT_CHARS = 100_000
MAX_REFERENCE_DOCS = 50
MAX_REFERENCE_CHARS = 1_000_000
MAX_TOTAL_REFERENCE_CHARS = 5_000_000
MAX_CLAIMS = 200
MAX_CLAIM_CHARS = 1_000
MAX_PASSAGES_PER_CLAIM = 8
MAX_PASSAGE_CHARS = 4_000
MAX_RATIONALE_CHARS = 2_000
MAX_ERROR_MESSAGE_CHARS = 500
MAX_TITLE_CHARS = 500
MAX_LABEL_CHARS = 64


def sha256_text(text: str) -> str:
    """The hex SHA-256 of ``text`` encoded as UTF-8. Used to pin offsets to an exact text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must contain non-whitespace text")
    return value


# --- Identifiers -------------------------------------------------------------------------------

# Identifiers issued by other members' systems (tenants, documents, requests). Opaque to the
# engine; the pattern only rules out values that are unsafe in logs, URLs and file names.
_EXTERNAL_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"

TenantId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]
DocumentId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]
RequestId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]
RecordId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]

# Identifiers issued by the engine. The prefix makes a claim id and a passage id impossible to
# confuse in logs or when one is passed where the other is expected.
ClaimId = Annotated[str, Field(pattern=r"^clm_[A-Za-z0-9_-]{1,64}$")]
PassageId = Annotated[str, Field(pattern=r"^psg_[A-Za-z0-9_-]{1,64}$")]

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Label = Annotated[str, Field(min_length=1, max_length=MAX_LABEL_CHARS), AfterValidator(_not_blank)]
Offset = Annotated[int, Field(strict=True, ge=0)]


def _text(max_length: int) -> Any:
    """Non-blank text of at most ``max_length`` code points, kept exactly as given."""
    return Annotated[str, Field(min_length=1, max_length=max_length), AfterValidator(_not_blank)]


ContentText = _text(MAX_CONTENT_CHARS)
ReferenceText = _text(MAX_REFERENCE_CHARS)
ClaimText = _text(MAX_CLAIM_CHARS)
PassageText = _text(MAX_PASSAGE_CHARS)
ErrorMessage = _text(MAX_ERROR_MESSAGE_CHARS)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _hash_of_text(data: dict[str, Any]) -> str:
    """Default for ``text_sha256``: computed from the already-validated ``text``."""
    text = data.get("text")
    return sha256_text(text) if isinstance(text, str) else ""


def _check_hash(text: str, given: str) -> None:
    if given != sha256_text(text):
        raise ValueError("text_sha256 does not match the SHA-256 of text")


# --- Locations ---------------------------------------------------------------------------------


class SourceSpan(_Contract):
    """A half-open ``[start, end)`` range of code points in one specific text."""

    start: Offset
    end: Offset

    @model_validator(mode="after")
    def _check_order(self) -> SourceSpan:
        if self.end <= self.start:
            raise ValueError("span end must be greater than span start")
        return self

    @property
    def length(self) -> int:
        return self.end - self.start

    def contains(self, other: SourceSpan) -> bool:
        return self.start <= other.start and other.end <= self.end

    def fits(self, text_length: int) -> bool:
        return self.end <= text_length

    def slice(self, text: str) -> str:
        return text[self.start : self.end]


# --- Inputs ------------------------------------------------------------------------------------


class InputContent(_Contract):
    """The content under review, already converted to plain text by the caller."""

    content_id: DocumentId | None = None
    text: ContentText
    # Optional on input: computed from ``text`` when omitted, rejected when it disagrees.
    text_sha256: Sha256Hex = Field(default_factory=_hash_of_text)

    @model_validator(mode="after")
    def _check_text_hash(self) -> InputContent:
        _check_hash(self.text, self.text_sha256)
        return self


class ReferenceDocument(_Contract):
    """One approved source of truth, already converted to plain text by the caller."""

    doc_id: DocumentId
    version: Label | None = None
    title: Annotated[str, Field(max_length=MAX_TITLE_CHARS)] | None = None
    text: ReferenceText
    # Optional on input: computed from ``text`` when omitted, rejected when it disagrees.
    text_sha256: Sha256Hex = Field(default_factory=_hash_of_text)

    @model_validator(mode="after")
    def _check_text_hash(self) -> ReferenceDocument:
        _check_hash(self.text, self.text_sha256)
        return self

    def descriptor(self) -> ReferenceDescriptor:
        return ReferenceDescriptor(doc_id=self.doc_id, version=self.version, text_sha256=self.text_sha256)


class ReferenceDescriptor(_Contract):
    """Identifies an exact reference text without carrying it. Used for provenance in reports."""

    doc_id: DocumentId
    version: Label | None = None
    text_sha256: Sha256Hex


class VerificationRequest(_Contract):
    """What a caller sends to verify one piece of content against its reference documents."""

    contract_version: ContractVersion = CONTRACT_VERSION
    request_id: RequestId
    tenant_id: TenantId
    content: InputContent
    references: Annotated[list[ReferenceDocument], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)]

    @model_validator(mode="after")
    def _check_references(self) -> VerificationRequest:
        duplicates = sorted(d for d, n in Counter(r.doc_id for r in self.references).items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate reference doc_id: {', '.join(duplicates)}")
        total = sum(len(r.text) for r in self.references)
        if total > MAX_TOTAL_REFERENCE_CHARS:
            raise ValueError(f"reference documents exceed {MAX_TOTAL_REFERENCE_CHARS} characters in total")
        return self


# --- Claims and evidence -----------------------------------------------------------------------


class Claim(_Contract):
    """One atomic, checkable statement extracted from the content.

    ``text`` is the claim as the verifier sees it and may be reworded to stand alone.
    ``source_span`` locates the words it came from in ``InputContent.text``.
    """

    claim_id: ClaimId
    text: ClaimText
    source_span: SourceSpan


class RetrievalMethod(str, Enum):
    BM25 = "bm25"


class RetrievalProvenance(_Contract):
    """How a passage was found. Scores are only comparable within one retrieval call."""

    method: RetrievalMethod
    score: Annotated[float, Field(allow_inf_nan=False)]
    rank: Annotated[int, Field(strict=True, ge=1)]


class EvidencePassage(_Contract):
    """A verbatim excerpt of one reference document, located by offsets into that document."""

    passage_id: PassageId
    doc_id: DocumentId
    doc_text_sha256: Sha256Hex
    span: SourceSpan
    text: PassageText
    retrieval: RetrievalProvenance

    @model_validator(mode="after")
    def _check_length(self) -> EvidencePassage:
        if len(self.text) != self.span.length:
            raise ValueError("passage text length does not match its span")
        return self

    def matches(self, document: ReferenceDocument) -> bool:
        """True when this passage is exactly the given document's text at ``span``."""
        return (
            self.doc_id == document.doc_id
            and self.doc_text_sha256 == document.text_sha256
            and self.span.fits(len(document.text))
            and self.span.slice(document.text) == self.text
        )


class ClaimVerificationInput(_Contract):
    """Everything the verifier is allowed to see: one claim and the passages retrieved for it.

    The reference corpus is deliberately absent. A claim with no retrieved passages never
    reaches the verifier; the engine records NOT_ENOUGH_EVIDENCE for it directly.
    """

    claim: Claim
    passages: Annotated[list[EvidencePassage], Field(min_length=1, max_length=MAX_PASSAGES_PER_CLAIM)]

    @model_validator(mode="after")
    def _check_unique(self) -> ClaimVerificationInput:
        _require_unique_passages(self.passages)
        return self


# --- Verdicts, citations, corrections, errors --------------------------------------------------


class Verdict(str, Enum):
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"
    ERROR = "ERROR"


class Citation(_Contract):
    """An exact quote from one evidence passage, located in the original reference document.

    ``quote_span`` is in reference-document coordinates (the same as ``EvidencePassage.span``),
    so a citation can be checked against the original text without the passage.
    """

    doc_id: DocumentId
    doc_text_sha256: Sha256Hex
    passage_id: PassageId
    quote: PassageText
    quote_span: SourceSpan

    @model_validator(mode="after")
    def _check_length(self) -> Citation:
        if len(self.quote) != self.quote_span.length:
            raise ValueError("quote length does not match quote_span")
        return self

    def matches(self, document: ReferenceDocument) -> bool:
        """True when ``quote`` is exactly the given document's text at ``quote_span``."""
        return (
            self.doc_id == document.doc_id
            and self.doc_text_sha256 == document.text_sha256
            and self.quote_span.fits(len(document.text))
            and self.quote_span.slice(document.text) == self.quote
        )


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[str]:
    """Numeric tokens in ``text``, with thousands separators removed (``1,200`` -> ``1200``)."""
    return {token.replace(",", "") for token in _NUMBER.findall(text)}


class Correction(_Contract):
    """A proposed replacement for part of the content, justified only by its citations.

    Contract-level guard: any number the replacement introduces must appear in a cited quote.
    Full fact checking of the replacement (names, units, re-verification) is the correction
    stage's job; this rule only makes the most common fabrication unrepresentable.
    """

    target_span: SourceSpan
    original_text: ClaimText
    replacement_text: ClaimText
    citations: Annotated[list[Citation], Field(min_length=1, max_length=MAX_PASSAGES_PER_CLAIM)]

    @model_validator(mode="after")
    def _check(self) -> Correction:
        if len(self.original_text) != self.target_span.length:
            raise ValueError("original_text length does not match target_span")
        if self.replacement_text == self.original_text:
            raise ValueError("replacement_text must differ from original_text")
        introduced = numbers_in(self.replacement_text) - numbers_in(self.original_text)
        cited = set().union(*(numbers_in(c.quote) for c in self.citations))
        unsupported = sorted(introduced - cited)
        if unsupported:
            raise ValueError(f"replacement introduces numbers not found in any cited quote: {', '.join(unsupported)}")
        return self


class PipelineStage(str, Enum):
    REQUEST = "request"
    EXTRACTION = "extraction"
    RETRIEVAL = "retrieval"
    VERIFICATION = "verification"
    CITATION_VALIDATION = "citation_validation"
    CORRECTION = "correction"
    SCORING = "scoring"


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_QUOTA_EXCEEDED = "PROVIDER_QUOTA_EXCEEDED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    MALFORMED_MODEL_OUTPUT = "MALFORMED_MODEL_OUTPUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ProcessingError(_Contract):
    """A failure the caller can act on.

    ``message`` is shown to clients: it must never contain secrets, prompts, raw provider
    responses or document text.
    """

    code: ErrorCode
    stage: PipelineStage
    message: ErrorMessage
    retryable: Annotated[bool, Field(strict=True)]
    claim_id: ClaimId | None = None


def _require_unique_passages(passages: list[EvidencePassage]) -> None:
    duplicates = sorted(p for p, n in Counter(p.passage_id for p in passages).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate passage_id: {', '.join(duplicates)}")


def _citation_key(citation: Citation) -> tuple[str, int, int]:
    return (citation.passage_id, citation.quote_span.start, citation.quote_span.end)


class ClaimResult(_Contract):
    """The outcome for one claim.

    Verdict rules:

    * SUPPORTED / CONTRADICTED: at least one citation; no error.
    * NOT_ENOUGH_EVIDENCE: no citations, no correction, no error. ``evidence`` may still list
      the passages that were considered.
    * ERROR: an error; no citations, no correction.
    * A correction is only allowed on CONTRADICTED, must stay inside the claim's source span,
      and may only cite quotes that are also citations of this result.
    * Every citation must quote, verbatim, a passage listed in ``evidence``.
    """

    claim: Claim
    verdict: Verdict
    evidence: Annotated[list[EvidencePassage], Field(max_length=MAX_PASSAGES_PER_CLAIM)] = []
    citations: Annotated[list[Citation], Field(max_length=MAX_PASSAGES_PER_CLAIM)] = []
    correction: Correction | None = None
    error: ProcessingError | None = None
    # Model-generated explanation, for display only. Never evidence; never checked against sources.
    model_rationale: Annotated[str, Field(max_length=MAX_RATIONALE_CHARS)] | None = None

    @model_validator(mode="after")
    def _check(self) -> ClaimResult:
        self._check_verdict_shape()
        _require_unique_passages(self.evidence)
        self._check_citations()
        self._check_correction()
        return self

    def _check_verdict_shape(self) -> None:
        verdict = self.verdict
        if verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED) and not self.citations:
            raise ValueError(f"{verdict.value} requires at least one citation")
        if verdict in (Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR) and self.citations:
            raise ValueError(f"{verdict.value} must not carry citations")
        if verdict is Verdict.ERROR and self.error is None:
            raise ValueError("ERROR requires an error")
        if verdict is not Verdict.ERROR and self.error is not None:
            raise ValueError(f"{verdict.value} must not carry an error")
        if self.correction is not None and verdict is not Verdict.CONTRADICTED:
            raise ValueError("a correction is only allowed on a CONTRADICTED claim")
        if self.error is not None and self.error.claim_id not in (None, self.claim.claim_id):
            raise ValueError("error.claim_id does not match the claim")

    def _check_citations(self) -> None:
        passages = {p.passage_id: p for p in self.evidence}
        seen: set[tuple[str, int, int]] = set()
        for citation in self.citations:
            passage = passages.get(citation.passage_id)
            if passage is None:
                raise ValueError(f"citation references passage {citation.passage_id} which is not in evidence")
            if citation.doc_id != passage.doc_id or citation.doc_text_sha256 != passage.doc_text_sha256:
                raise ValueError(f"citation of {citation.passage_id} names a different document than the passage")
            if not passage.span.contains(citation.quote_span):
                raise ValueError(f"citation quote_span lies outside passage {citation.passage_id}")
            offset = passage.span.start
            excerpt = passage.text[citation.quote_span.start - offset : citation.quote_span.end - offset]
            if excerpt != citation.quote:
                raise ValueError(f"citation quote is not the verbatim text of passage {citation.passage_id}")
            key = _citation_key(citation)
            if key in seen:
                raise ValueError(f"duplicate citation of {citation.passage_id}")
            seen.add(key)

    def _check_correction(self) -> None:
        if self.correction is None:
            return
        if not self.claim.source_span.contains(self.correction.target_span):
            raise ValueError("correction target_span lies outside the claim's source_span")
        cited = {_citation_key(c) for c in self.citations}
        if any(_citation_key(c) not in cited for c in self.correction.citations):
            raise ValueError("correction cites a quote that is not a citation of this result")


# --- Report ------------------------------------------------------------------------------------


class ReportStatus(str, Enum):
    COMPLETED = "COMPLETED"  # every claim has a non-ERROR verdict and no request-level error
    PARTIAL = "PARTIAL"  # at least one ERROR verdict or request-level error, some results usable
    FAILED = "FAILED"  # no results; see errors


class EngineProvenance(_Contract):
    """What produced a report, so results can be reproduced and compared across versions."""

    engine_version: Label
    contract_version: ContractVersion = CONTRACT_VERSION
    retrieval_method: RetrievalMethod
    model_id: Label | None = None
    prompt_versions: dict[Label, Label] = {}


class VerificationReport(_Contract):
    """What the engine returns for one VerificationRequest."""

    contract_version: ContractVersion = CONTRACT_VERSION
    request_id: RequestId
    tenant_id: TenantId
    content_sha256: Sha256Hex
    content_length: Annotated[int, Field(strict=True, ge=1, le=MAX_CONTENT_CHARS)]
    references: Annotated[list[ReferenceDescriptor], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)]
    status: ReportStatus
    results: Annotated[list[ClaimResult], Field(max_length=MAX_CLAIMS)] = []
    errors: list[ProcessingError] = []
    provenance: EngineProvenance

    @model_validator(mode="after")
    def _check(self) -> VerificationReport:
        self._check_status()
        self._check_claims()
        self._check_provenance()
        return self

    def _check_status(self) -> None:
        has_error_verdict = any(r.verdict is Verdict.ERROR for r in self.results)
        if self.status is ReportStatus.COMPLETED and (has_error_verdict or self.errors):
            raise ValueError("COMPLETED report must not contain ERROR verdicts or errors")
        if self.status is ReportStatus.PARTIAL and not (has_error_verdict or self.errors):
            raise ValueError("PARTIAL report must contain an ERROR verdict or an error")
        if self.status is ReportStatus.PARTIAL and not self.results:
            raise ValueError("PARTIAL report must contain results; use FAILED")
        if self.status is ReportStatus.FAILED and (self.results or not self.errors):
            raise ValueError("FAILED report must contain errors and no results")

    def _check_claims(self) -> None:
        ids = Counter(r.claim.claim_id for r in self.results)
        duplicates = sorted(c for c, n in ids.items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate claim_id: {', '.join(duplicates)}")
        for result in self.results:
            if not result.claim.source_span.fits(self.content_length):
                raise ValueError(f"claim {result.claim.claim_id} source_span exceeds content_length")

    def _check_provenance(self) -> None:
        known = {(r.doc_id, r.text_sha256) for r in self.references}
        if len({doc_id for doc_id, _ in known}) != len(self.references):
            raise ValueError("duplicate reference doc_id")
        for result in self.results:
            for passage in result.evidence:
                if (passage.doc_id, passage.doc_text_sha256) not in known:
                    raise ValueError(f"passage {passage.passage_id} comes from a document not in references")

    def verdict_counts(self) -> dict[Verdict, int]:
        counts = Counter(r.verdict for r in self.results)
        return {verdict: counts.get(verdict, 0) for verdict in Verdict}


# --- Evaluation --------------------------------------------------------------------------------


class GoldEvidence(_Contract):
    """Where in a reference document the evidence for a labelled claim lies.

    Gold evidence is located by document offsets, not passage ids, so the labels survive
    changes to how documents are split into passages. ``quote`` repeats the text at ``span`` so
    a reviewer can check the label without counting characters; it must match exactly.
    """

    doc_id: DocumentId
    span: SourceSpan
    quote: PassageText


class EvalSplit(str, Enum):
    DEV = "dev"  # used while building and tuning the engine
    HELDOUT = "heldout"  # reported separately; not used for tuning prompts or thresholds


class EvalCategory(str, Enum):
    """What makes an example hard. Independent of the expected verdict."""

    NUMERIC = "numeric"
    DATE = "date"
    NAMED_ENTITY = "named_entity"
    COMPOUND = "compound"  # more than one checkable part
    AMBIGUOUS = "ambiguous"  # vague or open to more than one reading
    NEGATION = "negation"
    PARAPHRASE = "paraphrase"  # same fact, different wording from the source
    DISTRACTOR = "distractor"  # references contain similar but non-matching facts
    MULTI_DOCUMENT = "multi_document"  # evidence is spread across documents
    ABSENT_FACT = "absent_fact"  # references cover the topic but not the fact
    IRRELEVANT_REFERENCES = "irrelevant_references"  # references do not cover the topic at all
    PROMPT_INJECTION = "prompt_injection"  # a reference contains instructions aimed at the model


class EvalRecord(_Contract):
    """One labelled example for the claim-verification evaluation set (one JSONL line).

    Labels only: an EvalRecord never carries a prediction, and a prediction never carries a label.
    """

    record_id: RecordId
    split: EvalSplit = EvalSplit.DEV
    claim_text: ClaimText
    references: Annotated[list[ReferenceDocument], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)]
    expected_verdict: Verdict
    gold_evidence: list[GoldEvidence] = []
    label_rationale: ClaimText
    categories: list[EvalCategory] = []
    tags: list[Label] = []
    # Who checked this label by hand. None means not yet reviewed by a person.
    reviewed_by: Label | None = None

    @model_validator(mode="after")
    def _check(self) -> EvalRecord:
        if self.expected_verdict is Verdict.ERROR:
            raise ValueError("ERROR is an engine outcome, not a label")
        needs_evidence = self.expected_verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED)
        if needs_evidence and not self.gold_evidence:
            raise ValueError(f"{self.expected_verdict.value} label requires gold_evidence")
        if not needs_evidence and self.gold_evidence:
            raise ValueError("NOT_ENOUGH_EVIDENCE label must not have gold_evidence")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("duplicate category")
        documents = {d.doc_id: d for d in self.references}
        if len(documents) != len(self.references):
            raise ValueError("duplicate reference doc_id")
        for gold in self.gold_evidence:
            document = documents.get(gold.doc_id)
            if document is None:
                raise ValueError(f"gold_evidence names unknown doc_id {gold.doc_id}")
            if not gold.span.fits(len(document.text)):
                raise ValueError(f"gold_evidence span exceeds document {gold.doc_id}")
            if gold.span.slice(document.text) != gold.quote:
                raise ValueError(f"gold_evidence quote is not the text at its span in {gold.doc_id}")
        return self
