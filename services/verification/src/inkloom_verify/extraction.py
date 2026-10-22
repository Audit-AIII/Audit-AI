"""Claim extraction: plain text in, atomic factual claims located in that text out.

The model classifies sentences and proposes claims; deterministic code decides what is kept.
Every claim is tied to a span of the input. If a proposed claim cannot be located, or its
rewording changes a number, month, qualifier, negation or attribution, or uses words that do
not occur in the content, the claim falls back to the verbatim sentence. Extraction can lose
atomicity this way, but never meaning, and never adds facts.

See PROMPTS.md for the prompt and the full rule list.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify.chunking import sentence_spans
from inkloom_verify.prompts import extraction as prompt
from inkloom_verify.providers.base import (
    ACCOUNT_ERRORS,
    JsonCompletionRequest,
    LLMProvider,
    MalformedOutputError,
    ProviderError,
)
from inkloom_verify.retrieval import tokenize
from inkloom_verify.security import clean_display_text
from inkloom_verify.schemas import (
    MAX_CLAIM_CHARS,
    MAX_CLAIMS,
    MAX_CONTENT_CHARS,
    Claim,
    ErrorCode,
    InputContent,
    PipelineStage,
    ProcessingError,
    Sha256Hex,
    SourceSpan,
    numbers_in,
    sha256_text,
)

logger = logging.getLogger(__name__)


class StatementKind(str, Enum):
    FACTUAL = "factual"
    OPINION = "opinion"
    STYLISTIC = "stylistic"
    OTHER = "other"


# --- What the model must return (validated; lengths are checked later, per claim) --------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# Caps on model output (see SECURITY.md). Claim text over MAX_CLAIM_CHARS but under the cap
# still falls back to the sentence with a warning; anything over a cap fails validation.
_MAX_MODEL_TEXT = 4_000


class _ModelClaim(_Strict):
    text: str = Field(max_length=_MAX_MODEL_TEXT)
    source_quote: str = Field(max_length=_MAX_MODEL_TEXT)


class _ModelStatement(_Strict):
    sentence_id: str = Field(max_length=32)
    kind: StatementKind
    claims: list[_ModelClaim] = Field(max_length=50)


class _ModelOutput(_Strict):
    statements: list[_ModelStatement] = Field(max_length=400)


# --- Configuration and result ------------------------------------------------------------------


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_sentences_per_call: Annotated[int, Field(strict=True, ge=1, le=200)] = 40
    max_output_tokens: Annotated[int, Field(strict=True, ge=256, le=32_000)] = 4_000
    max_claims: Annotated[int, Field(strict=True, ge=1, le=MAX_CLAIMS)] = MAX_CLAIMS
    max_claims_per_sentence: Annotated[int, Field(strict=True, ge=1, le=50)] = 10


class WarningCode(str, Enum):
    QUOTE_NOT_FOUND = "quote_not_found"  # source_quote is not in the sentence; used the sentence
    REWRITE_REJECTED = "rewrite_rejected"  # claim text changed the meaning; used the sentence
    CLAIM_TOO_LONG = "claim_too_long"  # claim text blank or over the limit; used the sentence
    FACTUAL_WITHOUT_CLAIMS = "factual_without_claims"  # sentence marked factual, no claims; used the sentence
    CLAIMS_ON_NON_FACTUAL = "claims_on_non_factual"  # claims listed for a non-factual sentence; ignored
    TOO_MANY_CLAIMS_IN_SENTENCE = "too_many_claims_in_sentence"  # extra claims ignored
    UNKNOWN_SENTENCE = "unknown_sentence"  # statement for a sentence id that was not sent; ignored
    DUPLICATE_STATEMENT = "duplicate_statement"  # second statement for a sentence; ignored
    SENTENCE_NOT_CLASSIFIED = "sentence_not_classified"  # model skipped a sentence; nothing extracted
    DUPLICATE_CLAIM = "duplicate_claim"  # same text and span as an earlier claim; dropped


class ExtractionWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: WarningCode
    sentence_id: str
    message: str


class ExtractedSentence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentence_id: str
    span: SourceSpan
    kind: StatementKind | None  # None: not classified (failed call or skipped by the model)
    claim_ids: list[str] = []


class ExtractionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_version: str
    provider: str
    sampling: dict[str, Any]
    models: list[str]
    calls: int


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    content_sha256: Sha256Hex
    claims: list[Claim]
    sentences: list[ExtractedSentence]
    warnings: list[ExtractionWarning]
    errors: list[ProcessingError]
    provenance: ExtractionProvenance

    @property
    def complete(self) -> bool:
        """True when every sentence was processed; False if any call failed or a limit was hit."""
        return not self.errors


# --- Meaning checks on a proposed rewrite ------------------------------------------------------

MONTHS = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b"
)
NEGATION = re.compile(r"\b(not|no|never|none|nor|neither|without|cannot)\b|n['’]t\b|\w-free\b")
QUALIFIERS = (
    "up to", "about", "approximately", "approx", "around", "at least", "at most", "more than",
    "less than", "fewer than", "nearly", "almost", "only", "roughly", "as much as", "as many as",
    "maximum", "minimum", "average", "typically", "estimated", "may", "might", "can", "could",
)
_ATTRIBUTION = re.compile(r"\b(according to|says|said|claims|claimed|reports|reported|states|stated)\b")


def _has(pattern: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(pattern)}\b", text) is not None


def rewrite_problems(claim: str, quote: str, content: str) -> list[str]:
    """Ways ``claim`` departs from the ``quote`` it was extracted from. Empty means acceptable."""
    claim_cf, quote_cf = claim.casefold(), quote.casefold()
    problems = []
    new_numbers = numbers_in(claim) - numbers_in(quote)
    if new_numbers:
        problems.append(f"changes or adds numbers ({', '.join(sorted(new_numbers))})")
    new_months = set(MONTHS.findall(claim_cf)) - set(MONTHS.findall(quote_cf))
    if new_months:
        problems.append(f"changes or adds months ({', '.join(sorted(new_months))})")
    if NEGATION.search(quote_cf) and not NEGATION.search(claim_cf):
        problems.append("drops a negation")
    dropped = [q for q in QUALIFIERS if _has(q, quote_cf) and not _has(q, claim_cf)]
    if dropped:
        problems.append(f"drops qualifiers ({', '.join(dropped)})")
    if _ATTRIBUTION.search(quote_cf) and not _ATTRIBUTION.search(claim_cf):
        problems.append("drops the attribution")
    unknown = sorted(set(tokenize(claim)) - set(tokenize(content)))
    if unknown:
        problems.append(f"uses words not in the content ({', '.join(unknown[:5])})")
    return problems


def _quote_pattern(quote: str) -> str:
    """Matches ``quote`` with any run of whitespace and either style of quotation mark."""
    alternatives = {"'": "['‘’]", "’": "['‘’]", '"': "[\"“”]",
                    "“": "[\"“”]", "”": "[\"“”]"}
    tokens = quote.split()
    return r"\s+".join("".join(alternatives.get(ch, re.escape(ch)) for ch in token) for token in tokens)


def locate(quote: str, sentence: str) -> tuple[int, int] | None:
    """Offsets of ``quote`` within ``sentence``, tolerating whitespace, quotation marks and case."""
    quote = quote.strip()
    if not quote:
        return None
    index = sentence.find(quote)
    if index >= 0:
        return index, index + len(quote)
    pattern = _quote_pattern(quote)
    match = re.search(pattern, sentence) or re.search(pattern, sentence, re.IGNORECASE)
    return (match.start(), match.end()) if match else None


# --- Extraction --------------------------------------------------------------------------------


@dataclass
class _CallStats:
    calls: int = 0
    models: set[str] = field(default_factory=set)


class ClaimExtractor:
    def __init__(self, provider: LLMProvider, config: ExtractionConfig | None = None) -> None:
        self.provider = provider
        self.config = config or ExtractionConfig()

    def extract(self, content: InputContent | str) -> ExtractionResult:
        stats = _CallStats()

        def result(**fields: Any) -> ExtractionResult:
            return ExtractionResult(
                provenance=ExtractionProvenance(
                    prompt_version=prompt.PROMPT_VERSION,
                    provider=self.provider.name,
                    sampling=self.provider.sampling(),
                    models=sorted(stats.models),
                    calls=stats.calls,
                ),
                **fields,
            )

        if isinstance(content, str):
            raw = content
            if not raw.strip() or len(raw) > MAX_CONTENT_CHARS:
                error = ProcessingError(
                    code=ErrorCode.INVALID_REQUEST,
                    stage=PipelineStage.EXTRACTION,
                    message=f"Content must contain text and be at most {MAX_CONTENT_CHARS} characters.",
                    retryable=False,
                )
                return result(content_sha256=sha256_text(raw), claims=[], sentences=[], warnings=[], errors=[error])
            content = InputContent(text=raw)
        elif not isinstance(content, InputContent):
            raise TypeError("content must be InputContent or str")

        text = content.text
        spans = [s for s in sentence_spans(text, MAX_CLAIM_CHARS) if any(ch.isalnum() for ch in s.slice(text))]
        sentences = {f"s{i}": span for i, span in enumerate(spans, start=1)}
        kinds: dict[str, StatementKind] = {}
        warnings: list[ExtractionWarning] = []
        errors: list[ProcessingError] = []
        proposed: list[tuple[str, str, SourceSpan]] = []  # (sentence_id, claim text, span)

        ids = list(sentences)
        size = self.config.max_sentences_per_call
        for start in range(0, len(ids), size):
            batch = ids[start : start + size]
            try:
                output = self._classify([(sid, sentences[sid].slice(text)) for sid in batch], stats)
            except ProviderError as error:
                errors.append(error.to_processing_error(PipelineStage.EXTRACTION))
                if isinstance(error, ACCOUNT_ERRORS) or error.code is ErrorCode.LIMIT_EXCEEDED:
                    break  # every further call would fail the same way
                continue
            proposed.extend(self._apply(output, batch, sentences, text, kinds, warnings))

        claims, claim_ids = self._number(proposed, warnings)
        if len(claims) > self.config.max_claims:
            dropped = len(claims) - self.config.max_claims
            claims = claims[: self.config.max_claims]
            kept = {c.claim_id for c in claims}
            claim_ids = {sid: [c for c in cids if c in kept] for sid, cids in claim_ids.items()}
            errors.append(
                ProcessingError(
                    code=ErrorCode.LIMIT_EXCEEDED,
                    stage=PipelineStage.EXTRACTION,
                    message=f"Only the first {self.config.max_claims} claims were kept; {dropped} were dropped.",
                    retryable=False,
                )
            )

        logger.info(
            "extraction sentences=%d claims=%d warnings=%d errors=%d calls=%d",
            len(sentences), len(claims), len(warnings), len(errors), stats.calls,
        )
        return result(
            content_sha256=content.text_sha256,
            claims=claims,
            sentences=[
                ExtractedSentence(sentence_id=sid, span=span, kind=kinds.get(sid), claim_ids=claim_ids.get(sid, []))
                for sid, span in sentences.items()
            ],
            warnings=warnings,
            errors=errors,
        )

    def _complete(self, request: JsonCompletionRequest, stats: _CallStats) -> dict[str, Any]:
        stats.calls += 1
        completion = self.provider.complete_json(request)
        stats.models.add(completion.model)
        return completion.data

    def _classify(self, batch: list[tuple[str, str]], stats: _CallStats) -> _ModelOutput:
        """Asks the model once, and once more with the problems listed if the reply is unusable."""
        request = JsonCompletionRequest(
            system=prompt.SYSTEM_PROMPT,
            user=prompt.user_message(batch),
            schema_name="claim_extraction",
            json_schema=prompt.OUTPUT_SCHEMA,
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            return _ModelOutput.model_validate(self._complete(request, stats))
        except ValidationError as error:
            problems = describe_validation_error(error)
        repair = request.model_copy(update={"user": prompt.repair_message(request.user, problems)})
        try:
            return _ModelOutput.model_validate(self._complete(repair, stats))
        except ValidationError:
            raise MalformedOutputError(
                "Claim extraction output did not match the schema after one repair attempt."
            ) from None

    def _apply(
        self,
        output: _ModelOutput,
        batch: list[str],
        sentences: dict[str, SourceSpan],
        text: str,
        kinds: dict[str, StatementKind],
        warnings: list[ExtractionWarning],
    ) -> list[tuple[str, str, SourceSpan]]:
        def warn(code: WarningCode, sentence_id: str, message: str) -> None:
            sid = clean_display_text(sentence_id, 64) or "?"
            warnings.append(ExtractionWarning(code=code, sentence_id=sid, message=message))

        proposed: list[tuple[str, str, SourceSpan]] = []
        expected = set(batch)
        for statement in output.statements:
            sid = statement.sentence_id
            if sid not in expected:
                warn(WarningCode.UNKNOWN_SENTENCE, sid, "statement for a sentence that was not sent")
                continue
            if sid in kinds:
                warn(WarningCode.DUPLICATE_STATEMENT, sid, "second statement for this sentence ignored")
                continue
            kinds[sid] = statement.kind
            span = sentences[sid]
            if statement.kind is not StatementKind.FACTUAL:
                if statement.claims:
                    warn(WarningCode.CLAIMS_ON_NON_FACTUAL, sid, f"{len(statement.claims)} claim(s) ignored")
                continue
            if not statement.claims:
                warn(WarningCode.FACTUAL_WITHOUT_CLAIMS, sid, "no claims listed; the sentence is used as the claim")
                proposed.append((sid, span.slice(text), span))
                continue
            limit = self.config.max_claims_per_sentence
            if len(statement.claims) > limit:
                warn(WarningCode.TOO_MANY_CLAIMS_IN_SENTENCE, sid, f"only the first {limit} claims kept")
            for model_claim in statement.claims[:limit]:
                proposed.append(self._ground(model_claim, sid, span, text, warn))
        for sid in batch:
            if sid not in kinds:
                warn(WarningCode.SENTENCE_NOT_CLASSIFIED, sid, "the model did not classify this sentence")
        return proposed

    @staticmethod
    def _ground(model_claim: _ModelClaim, sid: str, span: SourceSpan, text: str, warn: Any) -> tuple[str, str, SourceSpan]:
        """The claim with its location, or the verbatim sentence when the claim cannot be trusted."""
        sentence = span.slice(text)
        fallback = (sid, sentence, span)
        claim_text = model_claim.text.strip()
        if not claim_text or len(claim_text) > MAX_CLAIM_CHARS:
            warn(WarningCode.CLAIM_TOO_LONG, sid, "claim text blank or too long; the sentence is used")
            return fallback
        located = locate(model_claim.source_quote, sentence)
        if located is None:
            warn(WarningCode.QUOTE_NOT_FOUND, sid, "source_quote is not in the sentence; the sentence is used")
            return fallback
        quote_span = SourceSpan(start=span.start + located[0], end=span.start + located[1])
        problems = rewrite_problems(claim_text, quote_span.slice(text), text)
        if problems:
            warn(WarningCode.REWRITE_REJECTED, sid, "; ".join(problems) + "; the sentence is used")
            return fallback
        return sid, claim_text, quote_span

    @staticmethod
    def _number(
        proposed: list[tuple[str, str, SourceSpan]], warnings: list[ExtractionWarning]
    ) -> tuple[list[Claim], dict[str, list[str]]]:
        """Numbers claims clm_0001, clm_0002, ... in sentence order, dropping exact duplicates."""
        claims: list[Claim] = []
        by_sentence: dict[str, list[str]] = {}
        seen: set[tuple[str, int, int]] = set()
        for sid, claim_text, span in proposed:
            key = (claim_text, span.start, span.end)
            if key in seen:
                warnings.append(
                    ExtractionWarning(code=WarningCode.DUPLICATE_CLAIM, sentence_id=sid, message="duplicate claim dropped")
                )
                continue
            seen.add(key)
            claim = Claim(claim_id=f"clm_{len(claims) + 1:04d}", text=claim_text, source_span=span)
            claims.append(claim)
            by_sentence.setdefault(sid, []).append(claim.claim_id)
        return claims, by_sentence


def describe_validation_error(error: ValidationError) -> str:
    """The schema problems, without echoing any of the model's output."""
    parts = [
        f"{'.'.join(str(p) for p in e['loc']) or 'reply'}: {e['msg']}"
        for e in error.errors(include_input=False, include_url=False)[:5]
    ]
    return "; ".join(parts)
