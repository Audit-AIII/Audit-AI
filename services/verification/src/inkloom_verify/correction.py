"""Minimal, evidence-backed corrections for CONTRADICTED claims.

The model proposes a replacement; deterministic code decides whether it may be offered:

* only CONTRADICTED results with validated citations are ever sent (other verdicts, ERROR
  results and results already attempted are returned unchanged, without a model call);
* the model sees the author's sentence, the claim and the quotes that justified the
  contradiction, nothing else;
* the replaced text must be found in the claim's own source text;
* every word, number and currency or unit symbol the replacement adds must appear in the
  cited quotes (a short list of grammatical words is exempt), a figure must be the one the quotes
  give for the claim's property, and a compound part the replacement writes must be in the cited
  text;
* a qualifier ("up to", "about", "only", ...) used by both the original and the evidence
  must survive the edit;
* the edit must stay within the minimality bound (see ``minimality_limit``);
* the Correction contract must accept it;
* the corrected claim must re-verify as SUPPORTED against the same evidence (when re-checking
  is on, the default).

Anything that fails becomes NEEDS_HUMAN_REVIEW with the reasons; provider failures become
FAILED. The original claim and text are never changed: the proposal is recorded separately.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify.citation_guard import (
    full_dates,
    property_mismatch,
    quantities,
    uncovered_clauses,
)
from inkloom_verify.extraction import _ATTRIBUTION, QUALIFIERS, describe_validation_error, locate
from inkloom_verify.intent_lock import check_replacement, validate_locks
from inkloom_verify.prompts import correction as prompt
from inkloom_verify.prompts.loader import load_prompt
from inkloom_verify.providers.base import (
    JsonCompletionRequest,
    LLMProvider,
    MalformedOutputError,
    ProviderError,
)
from inkloom_verify.schemas import (
    MAX_CLAIM_CHARS,
    Citation,
    Claim,
    ClaimResult,
    ClaimVerificationInput,
    Correction,
    CorrectionAttempt,
    CorrectionIssue,
    CorrectionIssueCode,
    CorrectionStatus,
    InputContent,
    PipelineStage,
    SourceSpan,
    Verdict,
)
from inkloom_verify.security import (
    clean_display_text,
    has_hidden_characters,
    model_text_for_display,
)
from inkloom_verify.verification import ClaimVerifier

logger = logging.getLogger(__name__)

# Words a correction may add without evidence: they carry grammar, not facts. Modal and
# commitment words (will, can, may, always, guaranteed, only...) are deliberately absent.
NEUTRAL_WORDS = frozenset(
    "a an the of and is are was were be been to in on at for with by from as its it this that these those their our".split()
)
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")
_SYMBOL = re.compile(r"[€$£¥%°]")
MIN_EDIT_BOUND = 4


def words(text: str) -> list[str]:
    """Case-folded words and numbers; thousands separators are dropped (1,200 -> 1200)."""
    return [
        w.replace(",", "") for w in _WORD.findall(unicodedata.normalize("NFKC", text).casefold())
    ]


def _has_phrase(phrase: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def edit_distance(a: list[str], b: list[str]) -> int:
    """Word-level Levenshtein distance."""
    previous = list(range(len(b) + 1))
    for i, word_a in enumerate(a, start=1):
        current = [i]
        for j, word_b in enumerate(b, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (word_a != word_b))
            )
        previous = current
    return previous[-1]


def minimality_limit(original_words: int) -> int:
    """Largest word-level edit allowed: half the replaced words, but at least MIN_EDIT_BOUND."""
    return max(MIN_EDIT_BOUND, math.ceil(original_words / 2))


def correction_issues(
    original: str,
    replacement: str,
    quotes: list[str],
    before: str = "",
    after: str = "",
    passages: Sequence[str] = (),
) -> list[CorrectionIssue]:
    """Deterministic checks on one proposed replacement. Empty means it may be offered.

    ``before`` and ``after`` are the claim's text around ``original``. Figures are compared in that
    context, because a unit or currency often sits outside the replaced words ("€" + "99").
    ``passages`` are the cited passages; only the compound-part check reads them."""
    if not replacement.strip() or " ".join(replacement.split()) == " ".join(original.split()):
        return [CorrectionIssue(code=CorrectionIssueCode.NO_CHANGE)]
    issues = []
    evidence = set(words(" ".join(quotes)))
    added = sorted(set(words(replacement)) - set(words(original)) - NEUTRAL_WORDS - evidence)
    evidence_symbols = set(_SYMBOL.findall(" ".join(quotes)))
    symbols = sorted(
        set(_SYMBOL.findall(replacement)) - set(_SYMBOL.findall(original)) - evidence_symbols
    )
    old_text, new_text = before + original + after, before + replacement + after
    old_figures, new_figures, evidence_figures = (
        quantities(old_text),
        quantities(new_text),
        quantities(" ".join(quotes)),
    )
    # A new figure with a unit must appear in the evidence with that unit: "36" there may be hours.
    mispaired = sorted(
        f"{n} {u}"
        for n, u in new_figures - old_figures
        if u is not None and (n, u) not in evidence_figures
    )
    # A new whole date must be a whole date of the evidence, not a year borrowed from elsewhere.
    new_dates = full_dates(new_text) - full_dates(old_text) - full_dates(" ".join(quotes))
    unpaired = mispaired + sorted(f"{d[1]} {d[0]}" for d in new_dates)
    # A figure the evidence gives for another property: "hot for 24 hours" from "cold for up to 24
    # hours and hot for up to 12 hours". The same check the guard applies to SUPPORTED claims.
    if property_mismatch(new_text, quotes):
        unpaired.append("a figure the quotes give for another property")
    # A part of a compound rewrite that no cited text covers (the guard's unsupported_clause rule,
    # against the quotes and cited passages). Only parts the replacement writes are judged: an
    # untouched part is not the correction's statement (the re-check verifies it).
    start, end = len(before), len(before) + len(replacement)
    position = 0
    for part in uncovered_clauses(new_text, [*quotes, *passages]):
        s = new_text.find(part, position)
        e, position = s + len(part), s + len(part)
        if s < end and e > start:
            unpaired.append(f"{' '.join(new_text[max(s, start) : min(e, end)].split())!r}")
    if has_hidden_characters(replacement):
        unpaired.append("control or invisible characters")
    if added or symbols or unpaired:
        issues.append(
            CorrectionIssue(
                code=CorrectionIssueCode.UNSUPPORTED_ADDITION,
                detail=("adds, without evidence: " + ", ".join(added + symbols + unpaired))[:300],
            )
        )
    # A figure that loses its unit ("€99" -> "129"). A *swapped* unit ("5.2 kg" -> "5.2 g") keeps a
    # unit; whether the new one is right is the pairing check above (it must be in the evidence).
    old_units = sorted(u for _, u in old_figures if u is not None)
    new_units = sorted(u for _, u in new_figures if u is not None)
    if len(new_units) < len(old_units):
        dropped_units = sorted(set(old_units) - set(new_units)) or old_units
        issues.append(
            CorrectionIssue(
                code=CorrectionIssueCode.DROPS_UNIT,
                detail=("drops: " + ", ".join(dropped_units))[:300],
            )
        )
    # A figure with no unit deleted instead of fixed ("come in 4 colours" -> "come in colours"):
    # drops_unit can't see it and the re-check has no figure left to check. A new figure, or words
    # in its place (already required to be in the evidence, such as the quote's own list), is a fix.
    dropped_figures = sorted({n for n, u in old_figures if u is None} - {n for n, _ in new_figures})
    if (
        dropped_figures
        and not new_figures - old_figures
        and not set(words(replacement)) - set(words(original)) - NEUTRAL_WORDS
    ):
        issues.append(
            CorrectionIssue(
                code=CorrectionIssueCode.DROPS_FIGURE,
                detail=("drops: " + ", ".join(dropped_figures))[:300],
            )
        )
    # The source a sentence names for its fact must survive the fix.
    if len(_ATTRIBUTION.findall(old_text.casefold())) > len(
        _ATTRIBUTION.findall(new_text.casefold())
    ):
        issues.append(CorrectionIssue(code=CorrectionIssueCode.DROPS_ATTRIBUTION))
    evidence_text, original_cf, replacement_cf = (
        " ".join(quotes).casefold(),
        original.casefold(),
        replacement.casefold(),
    )
    kept_by_evidence = [
        q for q in QUALIFIERS if _has_phrase(q, original_cf) and _has_phrase(q, evidence_text)
    ]
    dropped = [q for q in kept_by_evidence if not _has_phrase(q, replacement_cf)]
    if dropped:
        issues.append(
            CorrectionIssue(
                code=CorrectionIssueCode.DROPS_QUALIFIER,
                detail=("drops: " + ", ".join(dropped))[:300],
            )
        )
    original_words, replacement_words = words(original), words(replacement)
    distance, limit = (
        edit_distance(original_words, replacement_words),
        minimality_limit(len(original_words)),
    )
    if distance > limit:
        issues.append(
            CorrectionIssue(
                code=CorrectionIssueCode.NOT_MINIMAL,
                detail=f"{distance} word edits; the limit is {limit}",
            )
        )
    return issues


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ModelOutput(_Strict):
    status: Literal["corrected", "needs_human_review"]
    original_text: str = Field(max_length=4_000)
    replacement_text: str = Field(max_length=4_000)
    citations: list[Annotated[str, Field(max_length=32)]] = Field(max_length=20)
    reason: str = Field(max_length=8_000)


class CorrectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_output_tokens: int = Field(default=1_000, ge=256, le=8_000)
    # The prompt file to load (prompts/<version>.txt). An exact version, never "latest".
    prompt_version: str = prompt.PROMPT_VERSION
    # Re-verify the corrected claim against the same evidence; the proposal stands only if
    # SUPPORTED.
    recheck: bool = True
    # Repair calls after a reply that does not match the schema (bounded; PROMPTS.md Phase 5).
    max_repairs: int = Field(default=1, ge=0, le=3)


class ClaimCorrector:
    def __init__(
        self,
        provider: LLMProvider,
        verifier: ClaimVerifier | None = None,
        config: CorrectionConfig | None = None,
    ) -> None:
        self.provider = provider
        self.verifier = verifier
        self.config = config or CorrectionConfig()
        self.prompt = load_prompt(
            "correction", self.config.prompt_version
        )  # fails clearly if missing
        self.prompt_sent = False
        self.models_used: set[str] = set()
        if self.config.recheck and verifier is None:
            raise ValueError("re-checking corrections needs a ClaimVerifier for the same request")

    def correct(
        self, result: ClaimResult, content: InputContent, locked_phrases: Sequence[str] = ()
    ) -> ClaimResult:
        """``result`` with a correction attempt added, or unchanged if no correction applies.

        ``locked_phrases`` (Intent-lock): a proposal that would remove locked text is refused with
        issue ``intent_lock`` before the re-check, whatever the evidence says; a person decides."""
        locks = validate_locks(locked_phrases)
        if (
            result.verdict is not Verdict.CONTRADICTED
            or not result.citations
            or result.correction_attempt is not None
        ):
            return result
        claim = result.claim
        if not claim.source_span.fits(len(content.text)):
            raise ValueError("the claim's source_span does not fit this content")
        sentence = claim.source_span.slice(content.text)
        labels = {f"C{i}": c for i, c in enumerate(result.citations, start=1)}
        request = JsonCompletionRequest(
            system=self.prompt.text,
            user=prompt.user_message(
                sentence, claim.statement, [(label, c.quote) for label, c in labels.items()]
            ),
            schema_name="claim_correction",
            json_schema=prompt.OUTPUT_SCHEMA,
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            output = self._ask(request)
        except ProviderError as error:
            failed = CorrectionAttempt(
                status=CorrectionStatus.FAILED,
                error=error.to_processing_error(PipelineStage.CORRECTION, claim.claim_id),
            )
            return _with(result, None, failed)

        if output.status == "needs_human_review":
            return _review(
                result,
                [
                    CorrectionIssue(
                        code=CorrectionIssueCode.MODEL_DECLINED,
                        detail=model_text_for_display(output.reason, 300, self.prompt.text),
                    )
                ],
            )

        issues: list[CorrectionIssue] = []
        cited: list[Citation] = []
        for label in dict.fromkeys(c.strip() for c in output.citations):
            if label in labels:
                cited.append(labels[label])
            else:
                issues.append(
                    CorrectionIssue(
                        code=CorrectionIssueCode.UNKNOWN_CITATION,
                        detail=clean_display_text(label, 300),
                    )
                )
        if not output.citations:
            issues.append(CorrectionIssue(code=CorrectionIssueCode.NO_CITATION))
        located = locate(output.original_text, sentence)
        if located is None:
            issues.append(CorrectionIssue(code=CorrectionIssueCode.TARGET_NOT_FOUND))
        if issues:
            return _review(result, issues)

        assert located is not None
        target = SourceSpan(
            start=claim.source_span.start + located[0], end=claim.source_span.start + located[1]
        )
        original = target.slice(content.text)
        replacement = output.replacement_text.strip()
        cited_passages = {c.passage_id for c in cited}
        issues = correction_issues(
            original,
            replacement,
            [c.quote for c in cited],
            before=sentence[: located[0]],
            after=sentence[located[1] :],
            passages=[p.text for p in result.evidence if p.passage_id in cited_passages],
        )
        if issues:
            return _review(result, issues)
        broken = check_replacement(content.text, target.start, target.end, replacement, locks)
        if broken:
            return _review(
                result,
                [
                    CorrectionIssue(
                        code=CorrectionIssueCode.INTENT_LOCK,
                        detail=f"would remove {len(broken)} locked phrase(s)",
                    )
                ],
            )
        try:
            correction = Correction(
                target_span=target,
                original_text=original,
                replacement_text=replacement,
                citations=cited,
            )
        except ValidationError as error:
            detail = describe_validation_error(error)[:300]
            return _review(
                result,
                [CorrectionIssue(code=CorrectionIssueCode.INVALID_CORRECTION, detail=detail)],
            )

        recheck_verdict = None
        if self.config.recheck:
            recheck_verdict, issue = self._recheck(result, sentence, located, original, replacement)
            if issue is not None:
                return _review(result, [issue], recheck_verdict)
        logger.info("correction claim=%s proposed", claim.claim_id)
        return _with(
            result,
            correction,
            CorrectionAttempt(status=CorrectionStatus.PROPOSED, recheck_verdict=recheck_verdict),
        )

    def _recheck(
        self,
        result: ClaimResult,
        sentence: str,
        located: tuple[int, int],
        original: str,
        replacement: str,
    ) -> tuple[Verdict | None, CorrectionIssue | None]:
        """Verifies the corrected claim against the same evidence. Only SUPPORTED lets it stand."""
        assert self.verifier is not None
        claim = result.claim
        if original in claim.statement:
            corrected = claim.statement.replace(original, replacement, 1)
        else:
            corrected = sentence[: located[0]] + replacement + sentence[located[1] :]
        if len(corrected) > MAX_CLAIM_CHARS:
            return None, CorrectionIssue(
                code=CorrectionIssueCode.RECHECK_UNAVAILABLE, detail="corrected claim too long"
            )
        checked = self.verifier.verify(
            ClaimVerificationInput(
                claim=Claim(
                    claim_id=claim.claim_id,
                    text=claim.text,
                    source_span=claim.source_span,
                    normalized_text=corrected if corrected != claim.text else None,
                ),
                passages=result.evidence,
            )
        )
        if checked.verdict is Verdict.ERROR:
            detail = checked.error.code.value if checked.error else None
            return None, CorrectionIssue(
                code=CorrectionIssueCode.RECHECK_UNAVAILABLE, detail=detail
            )
        if checked.verdict is not Verdict.SUPPORTED:
            return checked.verdict, CorrectionIssue(
                code=CorrectionIssueCode.RECHECK_NOT_SUPPORTED,
                detail=f"corrected claim re-checked as {checked.verdict.value}",
            )
        return checked.verdict, None

    def _ask(self, request: JsonCompletionRequest) -> _ModelOutput:
        """One call, then up to ``max_repairs`` repair calls listing the problems (never the reply)."""
        self.prompt_sent = True
        current = request
        for _ in range(self.config.max_repairs + 1):
            completion = self.provider.complete_json(current)
            self.models_used.add(completion.model)
            try:
                return _ModelOutput.model_validate(completion.data)
            except ValidationError as error:
                problems = describe_validation_error(error)
            current = request.model_copy(
                update={"user": prompt.repair_message(request.user, problems)}
            )
        raise MalformedOutputError(
            f"Correction output did not match the schema after {self.config.max_repairs} repair attempt(s)."
        )


def _with(
    result: ClaimResult, correction: Correction | None, attempt: CorrectionAttempt
) -> ClaimResult:
    """A validated copy of ``result`` with the correction fields set."""
    fields = {name: getattr(result, name) for name in ClaimResult.model_fields}
    return ClaimResult(**{**fields, "correction": correction, "correction_attempt": attempt})


def _review(
    result: ClaimResult, issues: list[CorrectionIssue], recheck_verdict: Verdict | None = None
) -> ClaimResult:
    logger.info(
        "correction claim=%s needs review: %s",
        result.claim.claim_id,
        ",".join(i.code.value for i in issues),
    )
    return _with(
        result,
        None,
        CorrectionAttempt(
            status=CorrectionStatus.NEEDS_HUMAN_REVIEW,
            issues=issues,
            recheck_verdict=recheck_verdict,
        ),
    )
