"""Suggested safer wording for NOT_ENOUGH_EVIDENCE (unverified) claims.

Product rules: docs/backend.md, "Safer wording for unverified claims". An unverified claim
has no evidence, so unlike a correction nothing can be checked against a quote: the suggestion may
only **remove or soften** what the claim already says. The model proposes; deterministic code
decides whether the proposal may be offered (``softening_issues``):

* only NOT_ENOUGH_EVIDENCE results without an error are sent (every other verdict, and a claim
  that itself gives instructions, returns None without a model call);
* the model sees the author's sentence and the claim, nothing else;
* the replaced text must be found in the claim's own source text;
* rule 1, never invent facts: no number, currency symbol, month or capitalised name that the
  claim did not already contain, and no added word outside ``SOFTENING_WORDS`` (grammatical
  words plus a short list of hedges and plain descriptions);
* rule 3, no unproven ranking or superlative anywhere in the rewritten claim (``RANKING_TERMS``),
  so swapping "number one" for "leading" is refused;
* rule 4, every number, currency symbol, month and capitalised name of the claim is kept;
* a real, small, single-line change with no hidden or control characters and no text that gives
  instructions.

Anything that fails, a model that declines, or a provider failure gives None. Rule 5 (the finding
stays unverified) is structural: this returns a separate ``SoftenedWording``, never a verdict, and
never touches the ``ClaimResult``. The backend re-checks every suggestion with its own guard
(services/api/src/inkloom_api/softening_guard.py), so these checks are at least as strict as it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from inkloom_verify.correction import NEUTRAL_WORDS, words
from inkloom_verify.extraction import describe_validation_error, locate
from inkloom_verify.intent_lock import check_replacement, validate_locks
from inkloom_verify.prompts import softening as prompt
from inkloom_verify.prompts.loader import load_prompt
from inkloom_verify.providers.base import JsonCompletionRequest, LLMProvider, MalformedOutputError, ProviderError
from inkloom_verify.schemas import ClaimResult, InputContent, SaferWording, SourceSpan, Verdict, numbers_in
from inkloom_verify.security import has_hidden_characters, instruction_like

logger = logging.getLogger(__name__)

# Unproven rankings and superlatives (rule 3). Includes every term of the backend's guard. Kept
# broad on purpose: a false refusal only means no suggestion is shown.
RANKING_TERMS = (
    "number one", "number 1", "no. 1", "no.1", "no 1", "#1", "best", "better", "leading", "fastest",
    "only", "top", "largest", "biggest", "cheapest", "most", "first", "greatest", "strongest",
    "ultimate", "unbeatable", "unmatched", "unrivalled", "unrivaled", "world-class", "best-selling",
    "industry-leading", "market-leading", "finest", "highest", "lowest", "smartest", "safest",
    "superior", "unique", "unparalleled", "favourite", "favorite", "premier", "foremost",
)
# Words a softened wording may add (rule 1). Grammatical words, plus hedges and plain
# descriptions that state no new fact. Deliberately short; product owners may tighten it.
# "sold" and "available" are here because the handoff's own example ("a smartphone sold in
# India") uses them: they restate that the product is offered, which the claim already implies.
SOFTENING_WORDS = NEUTRAL_WORDS | frozenset(
    "can may could help helps designed made intended aims aim offered offers sold available".split()
)
_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
)
_CURRENCY = re.compile(r"[€$£¥₹%]")
_CAPITALISED = re.compile(r"\b([A-Z][\w-]*)")
MAX_ADDED_WORDS = 3  # a softened wording removes; it may grow by at most this many words


def _has_term(term: str, text: str) -> bool:
    if term[0].isalnum() and term[-1].isalnum():
        return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text) is not None
    return term in text


def ranking_terms_in(text: str) -> list[str]:
    folded = text.casefold()
    return [term for term in RANKING_TERMS if _has_term(term, folded)]


def _months(text: str) -> set[str]:
    return {m for m in _MONTHS if _has_term(m, text.casefold())}


def names_in(text: str) -> set[str]:
    """Capitalised words, possessive dropped, ignoring the first word (sentence case), months and
    ranking terms (those are meant to go)."""
    tokens = text.split()
    first = re.sub(r"\W+$", "", tokens[0]) if tokens else ""
    names = set()
    for match in _CAPITALISED.finditer(text):
        word = match.group(1)
        stem = re.sub(r"['’]s$", "", word)
        if word == first or stem.casefold() in RANKING_TERMS or stem.casefold() in _MONTHS:
            continue
        names.add(stem)
    return names


def softening_issues(sentence: str, rewritten: str, original: str, replacement: str) -> list[str]:
    """Deterministic checks on one proposal. Empty means it may be offered.

    ``sentence`` is the claim's source text, ``rewritten`` the same text with ``original``
    replaced by ``replacement``. Whole-claim checks use those two, so a ranking left outside the
    edited part, or a name dropped by it, is caught."""
    if not replacement.strip() or " ".join(rewritten.split()) == " ".join(sentence.split()):
        return ["no_change"]
    issues = []
    if "\n" in replacement or "\r" in replacement or has_hidden_characters(replacement):
        issues.append("hidden_or_multiline")
    if instruction_like(replacement):
        issues.append("instruction_text")
    # Rule 1: never invent facts.
    added_numbers = numbers_in(rewritten) - numbers_in(sentence)
    if added_numbers:
        issues.append("adds_numbers:" + ",".join(sorted(added_numbers)))
    if set(_CURRENCY.findall(rewritten)) - set(_CURRENCY.findall(sentence)):
        issues.append("adds_currency")
    if _months(rewritten) - _months(sentence):
        issues.append("adds_date")
    added_names = sorted(names_in(rewritten) - names_in(sentence) - {w.capitalize() for w in words(sentence)})
    if added_names:
        issues.append("adds_names:" + ",".join(added_names))
    added_words = sorted(set(words(replacement)) - set(words(original)) - SOFTENING_WORDS)
    if added_words:
        issues.append("adds_words:" + ",".join(added_words))
    # Rule 3: no unproven ranking or superlative survives or appears.
    rankings = ranking_terms_in(rewritten)
    if rankings:
        issues.append("unproven_ranking:" + ",".join(rankings))
    # Rule 4: product names, prices and dates unchanged.
    if not numbers_in(sentence) <= numbers_in(rewritten):
        issues.append("drops_number")
    if not set(_CURRENCY.findall(sentence)) <= set(_CURRENCY.findall(rewritten)):
        issues.append("drops_currency")
    if not _months(sentence) <= _months(rewritten):
        issues.append("drops_date")
    missing = sorted(name for name in names_in(sentence) if name not in rewritten)
    if missing:
        issues.append("drops_name:" + ",".join(missing))
    # Minimal: softening removes; it may not grow the text much.
    if len(words(replacement)) > len(words(original)) + MAX_ADDED_WORDS:
        issues.append("not_minimal")
    return issues


# The contract type lives in schemas.py (ClaimResult.safer_wording). The handoff's name is kept as
# an alias so Member 3's backend code (load_softener_class) keeps working unchanged.
SoftenedWording = SaferWording


class _ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["softened", "needs_human_review"]
    original_text: str = Field(max_length=4_000)
    replacement_text: str = Field(max_length=4_000)
    citations: list[Annotated[str, Field(max_length=32)]] = Field(max_length=0)
    reason: str = Field(max_length=8_000)


class SofteningConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_output_tokens: int = Field(default=600, ge=256, le=8_000)
    # The prompt file to load (prompts/<version>.txt). An exact version, never "latest".
    prompt_version: str = prompt.PROMPT_VERSION
    # Repair calls after a reply that does not match the schema (bounded, as for corrections).
    max_repairs: int = Field(default=1, ge=0, le=3)


class ClaimSoftener:
    def __init__(self, provider: LLMProvider, config: SofteningConfig | None = None) -> None:
        self.provider = provider
        self.config = config or SofteningConfig()
        self.prompt = load_prompt("softening", self.config.prompt_version)  # fails clearly if missing
        self.prompt_sent = False
        self.models_used: set[str] = set()
        self.last_issues: list[str] = []  # why the last proposal was refused (codes only; for logs and tests)

    def soften(self, result: ClaimResult, content: InputContent, locked_phrases: Sequence[str] = ()) -> SoftenedWording | None:
        """For a NOT_ENOUGH_EVIDENCE result only (anything else -> None, no model call).
        Returns None when the model declines or any check fails, including Intent-lock: a wording
        that would remove a ``locked_phrases`` entry is refused (``last_issues`` = intent_lock)."""
        self.last_issues = []
        locks = validate_locks(locked_phrases)
        if result.verdict is not Verdict.NOT_ENOUGH_EVIDENCE or result.error is not None:
            return None
        claim = result.claim
        if not claim.source_span.fits(len(content.text)):
            raise ValueError("the claim's source_span does not fit this content")
        sentence = claim.source_span.slice(content.text)
        if instruction_like(sentence) or instruction_like(claim.statement):
            # Rewording a sentence that gives instructions would only republish them.
            self.last_issues = ["instruction_text"]
            return None
        request = JsonCompletionRequest(
            system=self.prompt.text,
            user=prompt.user_message(sentence, claim.statement),
            schema_name="claim_softening",
            json_schema=prompt.OUTPUT_SCHEMA,
            max_output_tokens=self.config.max_output_tokens,
        )
        try:
            output = self._ask(request)
        except ProviderError as error:
            self.last_issues = ["provider_error:" + error.code.value]
            logger.info("softening claim=%s failed: %s", claim.claim_id, error.code.value)
            return None
        if output.status == "needs_human_review":
            self.last_issues = ["model_declined"]
            return None

        located = locate(output.original_text, sentence)
        if located is None:
            self.last_issues = ["target_not_found"]
            return None
        target = SourceSpan(start=claim.source_span.start + located[0], end=claim.source_span.start + located[1])
        original = target.slice(content.text)
        replacement = output.replacement_text.strip()
        rewritten = sentence[: located[0]] + replacement + sentence[located[1] :]
        issues = softening_issues(sentence, rewritten, original, replacement)
        if not issues and check_replacement(content.text, target.start, target.end, replacement, locks):
            issues = ["intent_lock"]
        if issues:
            self.last_issues = issues
            logger.info("softening claim=%s refused: %s", claim.claim_id, ",".join(i.split(":")[0] for i in issues))
            return None
        try:
            wording = SoftenedWording(target_span=target, original_text=original, replacement_text=replacement)
        except ValidationError:
            self.last_issues = ["invalid_wording"]
            return None
        logger.info("softening claim=%s proposed", claim.claim_id)
        return wording

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
            current = request.model_copy(update={"user": prompt.repair_message(request.user, problems)})
        raise MalformedOutputError(
            f"Softening output did not match the schema after {self.config.max_repairs} repair attempt(s)."
        )
