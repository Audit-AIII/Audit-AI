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

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

from inkloom_verify.security import has_hidden_characters

ContractVersion = Literal["0.2.0"]
CONTRACT_VERSION: ContractVersion = "0.2.0"

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
# Names the set of reference documents a request is checked against. Issued by the backend and
# opaque to the engine: the engine never looks it up, it only carries it and checks it matches.
ReferenceSetId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]

# Identifiers issued by the engine. The prefix makes a claim id and a passage id impossible to
# confuse in logs or when one is passed where the other is expected.
ClaimId = Annotated[str, Field(pattern=r"^clm_[A-Za-z0-9_-]{1,64}$")]
PassageId = Annotated[str, Field(pattern=r"^psg_[A-Za-z0-9_-]{1,64}$")]

Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


def _single_clean_line(value: str) -> str:
    """Refuses control characters (NUL, line breaks, tabs), bidi overrides and zero-width
    characters (security.has_hidden_characters). Short identifiers and rule text are one visible
    line; NUL in particular cannot be stored by PostgreSQL, so the backend would refuse it later."""
    if has_hidden_characters(value):
        raise ValueError(
            "must not contain control characters (including NUL, tabs and line breaks), "
            "bidirectional overrides or zero-width characters"
        )
    return value


Label = Annotated[
    str,
    Field(min_length=1, max_length=MAX_LABEL_CHARS),
    AfterValidator(_not_blank),
    AfterValidator(_single_clean_line),
]
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
        return ReferenceDescriptor(
            doc_id=self.doc_id, version=self.version, text_sha256=self.text_sha256
        )


class ReferenceDescriptor(_Contract):
    """Identifies an exact reference text without carrying it. Used for provenance in reports."""

    doc_id: DocumentId
    version: Label | None = None
    text_sha256: Sha256Hex


# --- Brand rules (deterministic checks; rules.py) ------------------------------------------------
#
# Terminology, brand-compliance and accessibility rules. No model is involved. The entry point for
# the backend is rules.evaluate_rules (findings plus a per-rule check record); the engine pipeline
# applies VerificationRequest.rules through rules.check_rules. See RULES_HANDOFF.md.

MAX_RULES_PER_TYPE = 100
MAX_RULE_TEXT_CHARS = 500
MAX_RULE_FINDINGS = 200
MAX_METADATA_ITEMS = 500
# One clean line: rule terms, names, quotes, disclaimers, metadata refs, finding explanations.
RuleText = Annotated[
    str,
    Field(min_length=1, max_length=MAX_RULE_TEXT_CHARS),
    AfterValidator(_not_blank),
    AfterValidator(_single_clean_line),
]
RuleId = Annotated[str, Field(pattern=_EXTERNAL_ID_PATTERN)]
# A colour as written in CSS: #rgb, #rrggbb or rgb(r, g, b). Named colours are not accepted.
CssColor = Annotated[
    str,
    Field(
        pattern=r"^\s*(#[0-9A-Fa-f]{3}|#[0-9A-Fa-f]{6}|rgb\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\))\s*$"
    ),
]


class RuleType(str, Enum):
    # Terminology (category "terminology")
    REQUIRED_TERM = "required_term"  # the content must contain this term
    PROHIBITED_TERM = "prohibited_term"  # the content must not contain this term
    PRODUCT_NAMING = "product_naming"  # a product is written only as its approved name
    PREFERRED_TERM = "preferred_term"  # use the preferred term instead of the discouraged ones
    SPELLING = "spelling"  # a configured spelling convention ("e-mail" -> "email")
    TERMINOLOGY_CONSISTENCY = (
        "terminology_consistency"  # one of several accepted forms, used consistently
    )
    # Brand compliance (category "brand_compliance")
    REQUIRED_DISCLAIMER = (
        "required_disclaimer"  # this text must appear (always, or when a trigger term does)
    )
    NUMERIC_LIMIT = "numeric_limit"  # a figure about a subject stays within a range
    # Accessibility and tone (category "accessibility"; StyleRules, not brand-specific)
    ALL_CAPS_RUN = "all_caps_run"  # several shouted words in a row
    EMOJI_RUN = "emoji_run"  # more emoji in a row than allowed
    VAGUE_LINK_TEXT = (
        "vague_link_text"  # "click here" and other link text that says nothing out of context
    )
    MISSING_ALT_TEXT = "missing_alt_text"  # an image without a text alternative
    HEADING_STRUCTURE = "heading_structure"  # skipped heading levels, empty headings, several H1
    MISSING_CAPTIONS = "missing_captions"  # video without captions, audio without a transcript
    LOW_CONTRAST = "low_contrast"  # text colour against its background below the WCAG ratio


class RuleCategory(str, Enum):
    TERMINOLOGY = "terminology"
    BRAND_COMPLIANCE = "brand_compliance"
    ACCESSIBILITY = "accessibility"


RULE_CATEGORY: dict[RuleType, RuleCategory] = {
    **{
        t: RuleCategory.TERMINOLOGY
        for t in (
            RuleType.REQUIRED_TERM,
            RuleType.PROHIBITED_TERM,
            RuleType.PRODUCT_NAMING,
            RuleType.PREFERRED_TERM,
            RuleType.SPELLING,
            RuleType.TERMINOLOGY_CONSISTENCY,
        )
    },
    **{
        t: RuleCategory.BRAND_COMPLIANCE
        for t in (RuleType.REQUIRED_DISCLAIMER, RuleType.NUMERIC_LIMIT)
    },
    **{
        t: RuleCategory.ACCESSIBILITY
        for t in (
            RuleType.ALL_CAPS_RUN,
            RuleType.EMOJI_RUN,
            RuleType.VAGUE_LINK_TEXT,
            RuleType.MISSING_ALT_TEXT,
            RuleType.HEADING_STRUCTURE,
            RuleType.MISSING_CAPTIONS,
            RuleType.LOW_CONTRAST,
        )
    },
}


class RuleSeverity(str, Enum):  # the shared finding contract's values
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RuleSource(_Contract):
    """Where a rule is written down: one of the request's reference documents and the rule's
    exact wording in it. Checked against the request (the document must be one of its references
    and the quote must be in that document's text), so a rule finding's evidence is real."""

    doc_id: DocumentId
    quote: RuleText


class _Rule(_Contract):
    rule_id: RuleId
    severity: RuleSeverity = RuleSeverity.MEDIUM
    source: RuleSource | None = None


class _MatchOptions(_Contract):
    """How a rule's terms are matched (rules.term_pattern). Defaults: case-insensitive, whole
    words. Whitespace runs, straight and curly apostrophes, and hyphen variants always match each
    other; text and terms are compared in Unicode NFC, so "é" matches "e" + combining accent."""

    case_sensitive: bool = False
    whole_word: bool = True


def _same(a: str, b: str, case_sensitive: bool) -> bool:
    fold = (
        (lambda s: " ".join(s.split()))
        if case_sensitive
        else (lambda s: " ".join(s.split()).casefold())
    )
    return fold(a) == fold(b)


class RequiredTermRule(_Rule, _MatchOptions):
    term: RuleText


class ProhibitedTermRule(_Rule, _MatchOptions):
    term: RuleText
    # A brand-approved alternative, offered as the suggested correction for each match.
    approved_alternative: RuleText | None = None


class ProductNamingRule(_Rule):
    approved_name: RuleText
    # Other spellings to flag. Any case-insensitive match of the approved name that is not
    # written exactly as approved is flagged too.
    variants: Annotated[list[RuleText], Field(max_length=MAX_RULES_PER_TYPE)] = []


class PreferredTermRule(_Rule, _MatchOptions):
    """Each occurrence of a discouraged term is flagged; the preferred term is the suggestion."""

    preferred: RuleText
    discouraged: Annotated[list[RuleText], Field(min_length=1, max_length=MAX_RULES_PER_TYPE)]

    @model_validator(mode="after")
    def _check_terms(self) -> PreferredTermRule:
        if any(_same(d, self.preferred, self.case_sensitive) for d in self.discouraged):
            raise ValueError("the preferred term must not also be discouraged")
        return self


class SpellingRule(_Rule, _MatchOptions):
    """A configured spelling convention: each incorrect form is flagged with the correct one."""

    correct: RuleText
    incorrect: Annotated[list[RuleText], Field(min_length=1, max_length=MAX_RULES_PER_TYPE)]

    @model_validator(mode="after")
    def _check_terms(self) -> SpellingRule:
        if any(_same(i, self.correct, self.case_sensitive) for i in self.incorrect):
            raise ValueError("the correct spelling must not also be listed as incorrect")
        return self


class ConsistencyRule(_Rule, _MatchOptions):
    """Several accepted forms of one term ("email", "e-mail"); a document should use only one.
    When more than one is used, every occurrence of the less frequent forms is flagged. No
    correction is suggested: none of the forms is wrong, the brand has not picked one."""

    variants: Annotated[list[RuleText], Field(min_length=2, max_length=20)]

    @model_validator(mode="after")
    def _check_variants(self) -> ConsistencyRule:
        seen: list[str] = []
        for v in self.variants:
            if any(_same(v, s, self.case_sensitive) for s in seen):
                raise ValueError("consistency variants must be distinct")
            seen.append(v)
        return self


class RequiredDisclaimerRule(_Rule):
    disclaimer: RuleText
    # Required only when one of these terms appears; required always when empty.
    trigger_terms: Annotated[list[RuleText], Field(max_length=MAX_RULES_PER_TYPE)] = []


class NumericLimitRule(_Rule):
    """A figure in a sentence that mentions ``subject``, written with one of ``units``, must be
    within ``[minimum, maximum]``. "battery" + units ["hours", "hour", "h"] + maximum 24 flags
    "battery lasts 30 hours"."""

    subject: RuleText
    units: Annotated[list[RuleText], Field(min_length=1, max_length=20)]
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def _check_range(self) -> NumericLimitRule:
        if self.minimum is None and self.maximum is None:
            raise ValueError("a numeric rule needs a minimum, a maximum or both")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        return self


class StyleRules(_Contract):
    """Deterministic accessibility and tone checks (rules.py). Every check is on unless switched
    off; the thresholds are the defaults below. No model is involved and no source document is
    needed, so these findings carry no evidence and never a suggested correction."""

    severity: RuleSeverity = RuleSeverity.LOW
    # ALL-CAPS: at least this many consecutive words of two or more letters, all upper case.
    all_caps: bool = True
    all_caps_min_words: Annotated[int, Field(strict=True, ge=2, le=20)] = 3
    allowed_caps: Annotated[
        list[RuleText], Field(max_length=MAX_RULES_PER_TYPE)
    ] = []  # e.g. "USB-C", "IPX4"
    # Emoji: a run longer than this (spaces between emoji do not break a run).
    emoji: bool = True
    emoji_max_run: Annotated[int, Field(strict=True, ge=1, le=20)] = 2
    # Link text that says nothing out of context, compared case-insensitively to the whole link text.
    vague_link_text: bool = True
    vague_link_phrases: Annotated[
        list[RuleText], Field(min_length=1, max_length=MAX_RULES_PER_TYPE)
    ] = [
        "click here",
        "here",
        "read more",
        "learn more",
        "more",
        "this link",
        "link",
        "this page",
    ]
    # Images: Markdown ![](...) with empty alt text, HTML <img> with no alt attribute, and
    # ContentMetadata.images with alt_text None.
    alt_text: bool = True
    # Headings (Markdown "#" and HTML <h1>-<h6>): skipped levels, empty headings, more than one H1.
    heading_structure: bool = True
    # <video> without a captions/subtitles <track>; audio without a transcript (metadata only).
    media_captions: bool = True
    # Inline style colour pairs and ContentMetadata.colors below this ratio (WCAG 2 AA: 4.5, large text 3).
    color_contrast: bool = True
    min_contrast_ratio: Annotated[float, Field(ge=1.0, le=21.0)] = 4.5
    min_contrast_ratio_large_text: Annotated[float, Field(ge=1.0, le=21.0)] = 3.0


class ImageMetadata(_Contract):
    """An image the submitted text does not show (e.g. one in an uploaded file). alt_text None:
    no text alternative; "" : marked decorative (not flagged)."""

    ref: RuleText  # how a person finds it: a file name, "page 3, figure 2"
    alt_text: Annotated[str, Field(max_length=2_000)] | None = None


class MediaMetadata(_Contract):
    ref: RuleText
    kind: Literal["video", "audio"]
    captions: bool | None = None  # None: unknown
    transcript: bool | None = None  # None: unknown


class ColorPairMetadata(_Contract):
    ref: RuleText
    foreground: CssColor
    background: CssColor
    large_text: bool = False  # WCAG large text: at least 18 pt, or 14 pt bold


class ContentMetadata(_Contract):
    """Optional facts about content that plain text cannot carry (images, media and colours from
    an uploaded file). Each list is checked by the matching accessibility rule; an empty list is
    "nothing known", never "nothing there"."""

    images: Annotated[list[ImageMetadata], Field(max_length=MAX_METADATA_ITEMS)] = []
    media: Annotated[list[MediaMetadata], Field(max_length=MAX_METADATA_ITEMS)] = []
    colors: Annotated[list[ColorPairMetadata], Field(max_length=MAX_METADATA_ITEMS)] = []


class BrandRules(_Contract):
    """Explicit brand rules for one request, applied deterministically before claim extraction.

    Contradictory rules are refused when the rules are loaded, never resolved silently: a term
    both required and prohibited; a preferred, correct or approved term that is also prohibited;
    one discouraged/incorrect term mapped to two different replacements."""

    rule_set_id: RuleId
    version: Label | None = None
    required_terms: Annotated[list[RequiredTermRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    prohibited_terms: Annotated[list[ProhibitedTermRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    product_names: Annotated[list[ProductNamingRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    preferred_terms: Annotated[list[PreferredTermRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    spelling: Annotated[list[SpellingRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    consistency: Annotated[list[ConsistencyRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    disclaimers: Annotated[list[RequiredDisclaimerRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    numeric_limits: Annotated[list[NumericLimitRule], Field(max_length=MAX_RULES_PER_TYPE)] = []
    # Accessibility and tone checks; None means they are not run by the pipeline (evaluate_rules
    # runs them with the defaults unless told not to).
    style: StyleRules | None = None

    def all_rules(self) -> list[_Rule]:
        return [
            *self.required_terms,
            *self.prohibited_terms,
            *self.product_names,
            *self.preferred_terms,
            *self.spelling,
            *self.consistency,
            *self.disclaimers,
            *self.numeric_limits,
        ]

    @model_validator(mode="after")
    def _check_ids(self) -> BrandRules:
        duplicates = sorted(
            r for r, n in Counter(rule.rule_id for rule in self.all_rules()).items() if n > 1
        )
        if duplicates:
            raise ValueError(f"duplicate rule_id: {', '.join(duplicates)}")
        self._check_conflicts()
        return self

    def _check_conflicts(self) -> None:
        fold = lambda s: " ".join(s.split()).casefold()  # noqa: E731
        prohibited = {fold(r.term): r.rule_id for r in self.prohibited_terms}
        problems = []
        for rule in self.required_terms:
            if fold(rule.term) in prohibited:
                problems.append(
                    f"{rule.rule_id} requires a term that {prohibited[fold(rule.term)]} prohibits"
                )
        replacements: dict[str, tuple[str, str]] = {}  # discouraged -> (replacement, rule id)
        for rule, wanted, unwanted in (
            *((r, r.preferred, r.discouraged) for r in self.preferred_terms),
            *((r, r.correct, r.incorrect) for r in self.spelling),
        ):
            if fold(wanted) in prohibited:
                problems.append(
                    f"{rule.rule_id} recommends a term that {prohibited[fold(wanted)]} prohibits"
                )
            for term in unwanted:
                earlier = replacements.get(fold(term))
                if earlier and fold(earlier[0]) != fold(wanted):
                    problems.append(
                        f"{rule.rule_id} and {earlier[1]} map the same term to different replacements"
                    )
                replacements.setdefault(fold(term), (wanted, rule.rule_id))
        for rule in self.product_names:
            if fold(rule.approved_name) in prohibited:
                problems.append(
                    f"{rule.rule_id} approves a name that {prohibited[fold(rule.approved_name)]} prohibits"
                )
        if problems:
            raise ValueError("conflicting rules: " + "; ".join(problems))


class RuleEvidence(_Contract):
    """The shared contract's evidence item: a source id, the exact quote, and its relation."""

    source_id: DocumentId
    quote: RuleText
    relation: Literal["contradicts"] = "contradicts"  # the content breaks the quoted rule


class RuleFinding(_Contract):
    """One rule violation, in the shared finding contract's shape (check_type "rule").

    * ``span`` is always a non-empty range into the content (the backend stores span_end >
      span_start). ``scope`` "text": the span is the offending text. ``scope`` "document":
      something is missing (a required term, a disclaimer, an image's alt text known only from
      metadata), and the span anchors the finding on the content's first line.
    * ``verification_status`` is always ``not_applicable``: a rule check is not a claim checked
      against evidence. ``requires_human_review`` is always true: a person decides.
    * ``suggested_correction`` replaces ``original_text`` and exists only for terminology rules
      that name the wording to use. ``suggestion_basis`` says why it may be offered: the rule is
      quoted from an approved document ("approved_document", with evidence) or configured by
      the brand ("brand_rule"). Accessibility and compliance findings never carry one.
    """

    finding_id: Annotated[str, Field(pattern=r"^rul_[A-Za-z0-9_.:-]{1,160}$")]
    rule_id: RuleId
    rule_type: RuleType
    check_type: Literal["rule"] = "rule"
    category: RuleCategory
    severity: RuleSeverity
    scope: Literal["text", "document"] = "text"
    original_text: Annotated[str, Field(min_length=1, max_length=MAX_RULE_TEXT_CHARS)]
    span: SourceSpan
    explanation: RuleText
    verification_status: Literal["not_applicable"] = "not_applicable"
    source_ids: Annotated[list[DocumentId], Field(max_length=1)] = []
    evidence: Annotated[list[RuleEvidence], Field(max_length=1)] = []
    suggested_correction: RuleText | None = None
    suggestion_basis: Literal["approved_document", "brand_rule"] | None = None
    requires_human_review: Literal[True] = True

    @model_validator(mode="after")
    def _check(self) -> RuleFinding:
        if self.category is not RULE_CATEGORY[self.rule_type]:
            raise ValueError(
                f"category must be {RULE_CATEGORY[self.rule_type].value} for {self.rule_type.value}"
            )
        if self.span.length != len(self.original_text):
            raise ValueError("original_text does not match the span length")
        if [e.source_id for e in self.evidence] != self.source_ids:
            raise ValueError("source_ids must list the evidence's source ids")
        if (self.suggested_correction is None) != (self.suggestion_basis is None):
            raise ValueError("a suggested_correction needs a suggestion_basis, and only then")
        if self.suggested_correction is not None:
            if self.category is not RuleCategory.TERMINOLOGY:
                raise ValueError("only terminology findings may suggest a correction")
            if self.scope != "text":
                raise ValueError(
                    "a suggested_correction replaces quoted text; a document-level finding has none"
                )
            if self.suggestion_basis == "approved_document" and not self.evidence:
                raise ValueError(
                    "an approved_document suggestion needs the quoted rule as evidence"
                )
        return self


class RuleCheckStatus(str, Enum):
    PASSED = "passed"  # the check ran and found nothing
    VIOLATED = "violated"  # the check ran and produced findings
    NOT_CHECKABLE = "not_checkable"  # the input lacks what the check needs (no markup, no metadata)
    ERROR = "error"  # the check failed to run; never counted as passed


class RuleCheck(_Contract):
    """What happened to one rule, so "no finding" is never mistaken for "checked and fine"."""

    rule_id: RuleId
    rule_type: RuleType
    category: RuleCategory
    status: RuleCheckStatus
    findings: Annotated[int, Field(strict=True, ge=0)] = 0
    reason: Annotated[str, Field(max_length=300)] | None = (
        None  # why not checkable / what failed; never content
    )

    @model_validator(mode="after")
    def _check(self) -> RuleCheck:
        if self.category is not RULE_CATEGORY[self.rule_type]:
            raise ValueError("category does not match rule_type")
        if (self.status is RuleCheckStatus.VIOLATED) != (self.findings > 0):
            raise ValueError("a violated check has findings and only a violated check has findings")
        if (
            self.status in (RuleCheckStatus.NOT_CHECKABLE, RuleCheckStatus.ERROR)
            and not self.reason
        ):
            raise ValueError("a not_checkable or error check must say why")
        return self


class RuleEvaluation(_Contract):
    """The result of rules.evaluate_rules: every finding, and one check record per rule run.

    ``complete`` is false when any check ended in ERROR; ``truncated`` is true when more findings
    existed than MAX_RULE_FINDINGS (the checks still count them all)."""

    findings: Annotated[list[RuleFinding], Field(max_length=MAX_RULE_FINDINGS)] = []
    checks: list[RuleCheck] = []
    complete: Annotated[bool, Field(strict=True)]
    truncated: Annotated[bool, Field(strict=True)] = False

    @model_validator(mode="after")
    def _check(self) -> RuleEvaluation:
        if self.complete is any(c.status is RuleCheckStatus.ERROR for c in self.checks):
            raise ValueError("complete must be false exactly when a check ended in error")
        counted = sum(c.findings for c in self.checks)
        if (counted > len(self.findings)) is not self.truncated or counted < len(self.findings):
            raise ValueError(
                "findings must match the checks' counts (truncated only when some were dropped)"
            )
        if len({f.finding_id for f in self.findings}) != len(self.findings):
            raise ValueError("duplicate rule finding_id")
        return self


class VerificationRequest(_Contract):
    """What a caller sends to verify one piece of content against its reference documents."""

    contract_version: ContractVersion = CONTRACT_VERSION
    request_id: RequestId
    tenant_id: TenantId
    reference_set_id: ReferenceSetId | None = None
    content: InputContent
    references: Annotated[
        list[ReferenceDocument], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)
    ]
    # Explicit brand rules, checked deterministically before extraction (rules.py). Optional.
    rules: BrandRules | None = None
    # Intent-lock: exact phrases the writer marked as must-keep; no suggested correction or safer
    # wording may remove them (intent_lock.py). Optional.
    locked_phrases: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=200)]], Field(max_length=50)
    ] = []

    @model_validator(mode="after")
    def _check_references(self) -> VerificationRequest:
        duplicates = sorted(
            d for d, n in Counter(r.doc_id for r in self.references).items() if n > 1
        )
        if duplicates:
            raise ValueError(f"duplicate reference doc_id: {', '.join(duplicates)}")
        total = sum(len(r.text) for r in self.references)
        if total > MAX_TOTAL_REFERENCE_CHARS:
            raise ValueError(
                f"reference documents exceed {MAX_TOTAL_REFERENCE_CHARS} characters in total"
            )
        if any(not phrase.strip() for phrase in self.locked_phrases):
            raise ValueError("locked phrases must be non-blank")
        if self.rules is not None:
            # A rule's source must be one of this request's references, quoted verbatim: rule
            # evidence comes only from the authorised set, like claim evidence.
            texts = {r.doc_id: r.text for r in self.references}
            for rule in self.rules.all_rules():
                if rule.source is None:
                    continue
                if rule.source.doc_id not in texts:
                    raise ValueError(
                        f"rule {rule.rule_id} cites a document that is not a reference of this request"
                    )
                if rule.source.quote not in texts[rule.source.doc_id]:
                    raise ValueError(
                        f"rule {rule.rule_id} quotes text that is not in its source document"
                    )
        return self


# --- Claims and evidence -----------------------------------------------------------------------


class Claim(_Contract):
    """One atomic, checkable statement extracted from the content.

    ``text`` is exactly the content at ``source_span`` (``content[start:end] == text``; the
    lengths are checked here, the characters by ``scope.check_report_scope``, which has the
    content). ``normalized_text`` is the claim reworded to stand alone, when the extractor
    reworded it; it never adds facts (extraction.rewrite_problems). ``statement`` is what
    retrieval, the verifier and the corrector work on.
    """

    claim_id: ClaimId
    text: ClaimText
    source_span: SourceSpan
    normalized_text: ClaimText | None = None

    @model_validator(mode="after")
    def _check_text(self) -> Claim:
        if self.normalized_text is not None and has_hidden_characters(self.normalized_text):
            raise ValueError(
                "normalized_text must not contain control, bidi or zero-width characters"
            )
        if len(self.text) != self.source_span.length:
            raise ValueError(
                "claim text length does not match its source_span (text must be the exact content slice)"
            )
        if self.normalized_text is not None and self.normalized_text == self.text:
            raise ValueError(
                "normalized_text must differ from text; omit it when the claim was not reworded"
            )
        return self

    @property
    def statement(self) -> str:
        """The claim as checked: the standalone rewording if there is one, else the source text."""
        return self.normalized_text or self.text


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
    # The reference set the passage was retrieved from (contract 0.2.0). Optional; when present it
    # must equal the request's and the report's reference_set_id.
    reference_set_id: ReferenceSetId | None = None

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
    passages: Annotated[
        list[EvidencePassage], Field(min_length=1, max_length=MAX_PASSAGES_PER_CLAIM)
    ]

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
        if has_hidden_characters(self.replacement_text):
            raise ValueError(
                "replacement_text must not contain control, bidi or zero-width characters"
            )
        if len(self.original_text) != self.target_span.length:
            raise ValueError("original_text length does not match target_span")
        if self.replacement_text == self.original_text:
            raise ValueError("replacement_text must differ from original_text")
        introduced = numbers_in(self.replacement_text) - numbers_in(self.original_text)
        cited = set().union(*(numbers_in(c.quote) for c in self.citations))
        unsupported = sorted(introduced - cited)
        if unsupported:
            raise ValueError(
                f"replacement introduces numbers not found in any cited quote: {', '.join(unsupported)}"
            )
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
    PROVIDER_NOT_CONFIGURED = (
        "PROVIDER_NOT_CONFIGURED"  # no credentials or models set; AI checks unavailable
    )
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
    # Seconds the provider asked to wait (its Retry-After), for PROVIDER_RATE_LIMITED only.
    retry_after_seconds: Annotated[int, Field(strict=True, ge=0, le=3_600)] | None = None

    @model_validator(mode="after")
    def _check_retry_after(self) -> ProcessingError:
        if (
            self.retry_after_seconds is not None
            and self.code is not ErrorCode.PROVIDER_RATE_LIMITED
        ):
            raise ValueError("retry_after_seconds is only for PROVIDER_RATE_LIMITED")
        return self


def _require_unique_passages(passages: list[EvidencePassage]) -> None:
    duplicates = sorted(p for p, n in Counter(p.passage_id for p in passages).items() if n > 1)
    if duplicates:
        raise ValueError(f"duplicate passage_id: {', '.join(duplicates)}")


def _citation_key(citation: Citation) -> tuple[str, int, int]:
    return (citation.passage_id, citation.quote_span.start, citation.quote_span.end)


class CorrectionStatus(str, Enum):
    PROPOSED = "proposed"  # a correction passed every check and is offered to the reviewer
    NEEDS_HUMAN_REVIEW = "needs_human_review"  # no safe correction; a person must decide the fix
    FAILED = "failed"  # the correction stage could not run (provider or output failure)


class CorrectionIssueCode(str, Enum):
    MODEL_DECLINED = "model_declined"  # the model said the evidence does not determine a fix
    NO_CITATION = "no_citation"  # the proposal cites no evidence
    UNKNOWN_CITATION = "unknown_citation"  # cites evidence that did not justify the contradiction
    TARGET_NOT_FOUND = "target_not_found"  # the text to replace is not in the claim's source text
    NO_CHANGE = "no_change"  # the replacement is blank or the same as the original
    UNSUPPORTED_ADDITION = (
        "unsupported_addition"  # adds words, numbers or symbols absent from the cited evidence
    )
    NOT_MINIMAL = "not_minimal"  # rewrites more than the minimality bound allows
    DROPS_QUALIFIER = (
        "drops_qualifier"  # removes a qualifier ("up to", "about") that the evidence also uses
    )
    DROPS_UNIT = "drops_unit"  # removes a unit or currency from a figure ("€99" -> "129")
    DROPS_ATTRIBUTION = (
        "drops_attribution"  # removes "according to", "says", ... that the sentence had
    )
    RECHECK_NOT_SUPPORTED = (
        "recheck_not_supported"  # the corrected claim did not verify as SUPPORTED
    )
    RECHECK_UNAVAILABLE = "recheck_unavailable"  # the re-check could not run
    INVALID_CORRECTION = "invalid_correction"  # the proposal broke the Correction contract
    INTENT_LOCK = "intent_lock"  # the proposal would remove text the writer locked (intent_lock.py)


class CorrectionIssue(_Contract):
    code: CorrectionIssueCode
    detail: Annotated[str, Field(max_length=300)] | None = None


class CorrectionAttempt(_Contract):
    """What happened when a correction was attempted for a CONTRADICTED claim.

    PROPOSED: a correction is attached to the result and passed every check (and the re-check,
    when one ran). NEEDS_HUMAN_REVIEW: no correction is attached; ``issues`` says why.
    FAILED: no correction is attached; ``error`` says why.
    """

    status: CorrectionStatus
    issues: list[CorrectionIssue] = []
    recheck_verdict: Verdict | None = None  # verdict of the corrected claim, when re-checked
    error: ProcessingError | None = None

    @model_validator(mode="after")
    def _check(self) -> CorrectionAttempt:
        if self.status is CorrectionStatus.PROPOSED and (self.issues or self.error):
            raise ValueError("a PROPOSED correction has no issues and no error")
        if self.status is CorrectionStatus.PROPOSED and self.recheck_verdict not in (
            None,
            Verdict.SUPPORTED,
        ):
            raise ValueError("a PROPOSED correction must re-check as SUPPORTED")
        if self.status is CorrectionStatus.NEEDS_HUMAN_REVIEW and (not self.issues or self.error):
            raise ValueError("NEEDS_HUMAN_REVIEW lists issues and has no error")
        if self.status is CorrectionStatus.FAILED and self.error is None:
            raise ValueError("FAILED requires an error")
        return self


class EvidenceStrength(str, Enum):
    """How strongly the accepted evidence backs a definite verdict. An ordinal label from fixed
    rules (``evidence_strength``), not a probability: it has not been calibrated."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"
    NONE = "none"


_DIGIT = re.compile(r"\d")


def evidence_strength(
    verdict: Verdict, claim_text: str, evidence: list[Any], citations: list[Any]
) -> EvidenceStrength:
    """The approved rules (Phase 5), in order:

    * NONE: NOT_ENOUGH_EVIDENCE or ERROR (a downgraded answer is NOT_ENOUGH_EVIDENCE, so a
      rejected citation can never be rescued by rank, score or model confidence);
    * WEAK: a definite verdict, but no citation comes from the top-ranked passage;
    * STRONG: a citation comes from the top-ranked passage, and either there are two or more
      accepted citations, or the verdict is SUPPORTED and the claim has figures (digits), all of
      which the support checks matched in the quotes;
    * MODERATE: otherwise (one citation, from the top-ranked passage).

    Retrieval only enters through rank; scores are never compared across claims.
    """
    if verdict not in (Verdict.SUPPORTED, Verdict.CONTRADICTED) or not citations:
        return EvidenceStrength.NONE
    ranks = {p.passage_id: p.retrieval.rank for p in evidence}
    if not any(ranks.get(c.passage_id) == 1 for c in citations):
        return EvidenceStrength.WEAK
    if len(citations) >= 2 or (verdict is Verdict.SUPPORTED and _DIGIT.search(claim_text)):
        return EvidenceStrength.STRONG
    return EvidenceStrength.MODERATE


def _strength_default(data: dict[str, Any]) -> EvidenceStrength:
    if "verdict" not in data or "claim" not in data:
        return EvidenceStrength.NONE
    return evidence_strength(
        data["verdict"],
        data["claim"].statement,
        data.get("evidence", []),
        data.get("citations", []),
    )


def review_needed(verdict: Verdict, strength: EvidenceStrength) -> bool:
    """The approved review policy: every verdict except SUPPORTED, and SUPPORTED on weak evidence."""
    return verdict is not Verdict.SUPPORTED or strength is EvidenceStrength.WEAK


class ClaimReviewReason(str, Enum):
    """Why one claim goes to a person (EVAL.md Phase 5, decision-policy-v1).

    The first four are the fixed floor (``floor_review_reasons``): no configuration can remove
    them. The last two are added by a configurable ``DecisionPolicy`` (``decision_policy.py``),
    only to SUPPORTED claims: a policy can route more claims to review, never fewer.
    """

    CONTRADICTED = "contradicted"
    NOT_ENOUGH_EVIDENCE = (
        "not_enough_evidence"  # includes missing sources and conflicting references
    )
    ERROR = "error"
    WEAK_EVIDENCE = "weak_evidence"  # SUPPORTED, but no citation from the top-ranked passage
    BELOW_POLICY_STRENGTH = (
        "below_policy_strength"  # SUPPORTED, evidence below the policy's auto-clear minimum
    )
    COMPOUND_UNDER_CITED = (
        "compound_under_cited"  # SUPPORTED compound claim with too few accepted citations
    )


FLOOR_REVIEW_REASONS = frozenset(
    {
        ClaimReviewReason.CONTRADICTED,
        ClaimReviewReason.NOT_ENOUGH_EVIDENCE,
        ClaimReviewReason.ERROR,
        ClaimReviewReason.WEAK_EVIDENCE,
    }
)


def floor_review_reasons(verdict: Verdict, strength: EvidenceStrength) -> list[ClaimReviewReason]:
    """The fixed review floor (``review_needed`` as reasons); never configurable."""
    if verdict is Verdict.CONTRADICTED:
        return [ClaimReviewReason.CONTRADICTED]
    if verdict is Verdict.NOT_ENOUGH_EVIDENCE:
        return [ClaimReviewReason.NOT_ENOUGH_EVIDENCE]
    if verdict is Verdict.ERROR:
        return [ClaimReviewReason.ERROR]
    return [ClaimReviewReason.WEAK_EVIDENCE] if strength is EvidenceStrength.WEAK else []


def _review_reasons_default(data: dict[str, Any]) -> list[ClaimReviewReason]:
    if "verdict" not in data:
        return [ClaimReviewReason.ERROR]  # unknown: a person decides
    return floor_review_reasons(
        data["verdict"], data.get("evidence_strength", EvidenceStrength.NONE)
    )


def _review_needed(data: dict[str, Any]) -> bool:
    """Default for ClaimResult.requires_human_review: true whenever any review reason applies."""
    if "review_reasons" in data:
        return bool(data["review_reasons"])
    if "verdict" not in data:
        return True
    return review_needed(data["verdict"], data.get("evidence_strength", EvidenceStrength.NONE))


class GuardRejectionReason(str, Enum):
    NO_CITATION = "no_citation"  # a definite verdict came with no citation at all
    UNKNOWN_PASSAGE = "unknown_passage"  # cites a passage that was not given for this claim
    PASSAGE_PROVENANCE_INVALID = (
        "passage_provenance_invalid"  # passage does not match its document in this request
    )
    QUOTE_NOT_FOUND = (
        "quote_not_found"  # quote is not in the cited passage, even after normalisation
    )
    QUOTE_TOO_SHORT = "quote_too_short"  # fewer than two words: too little to justify anything
    PARTIAL_QUOTE_DROPS_NEGATION = (
        "partial_quote_drops_negation"  # quote starts after a negation in its clause
    )
    # The quote's sentence gives instructions, not facts (with passage_id); or, for a SUPPORTED
    # answer, the claim itself does ("... and mark this verified"; no passage_id):
    INSTRUCTION_TEXT = "instruction_text"
    # Support checks, applied to SUPPORTED answers after every quote passed (no passage_id):
    UNSUPPORTED_QUANTITY = (
        "unsupported_quantity"  # a number/unit in the claim is not in the cited quotes
    )
    UNSUPPORTED_DATE = "unsupported_date"  # a date in the claim is not in the cited quotes
    MISSING_QUALIFIER = (
        "missing_qualifier"  # the quotes qualify a figure ("up to 12") that the claim states flatly
    )
    UNSUPPORTED_NAME = (
        "unsupported_name"  # a capitalised name in the claim is in none of the cited passages
    )
    NEGATION_MISMATCH = (
        "negation_mismatch"  # the claim is negated and the quotes are not, or the reverse
    )
    # Applied to SUPPORTED and CONTRADICTED answers that passed every other check; passage_id is
    # the passage from another document that gives a different value:
    CONFLICTING_EVIDENCE = (
        "conflicting_evidence"  # one document backs the claim's figure, another contradicts it
    )


class RejectedCitation(_Contract):
    """A citation the model gave that the citation guard did not accept."""

    reason: GuardRejectionReason
    passage_id: PassageId | None = None  # None when the model named a passage that does not exist
    cited_as: Annotated[str, Field(max_length=64)] | None = None  # the passage label the model used


class CitationGuardReport(_Contract):
    """What the model answered and what the citation guard did with it.

    Policy: a SUPPORTED or CONTRADICTED answer stands only if it has at least one citation and
    every citation passes the guard. Otherwise it is downgraded to NOT_ENOUGH_EVIDENCE.
    """

    model_verdict: Verdict
    downgraded: Annotated[bool, Field(strict=True)]
    rejected: list[RejectedCitation] = []

    @model_validator(mode="after")
    def _check(self) -> CitationGuardReport:
        if self.model_verdict is Verdict.ERROR:
            raise ValueError("model_verdict cannot be ERROR; failures are reported as errors")
        definite = self.model_verdict in (Verdict.SUPPORTED, Verdict.CONTRADICTED)
        if self.downgraded and not definite:
            raise ValueError("only a SUPPORTED or CONTRADICTED answer can be downgraded")
        if self.downgraded and not self.rejected:
            raise ValueError("a downgrade must list why")
        if not self.downgraded and self.rejected:
            raise ValueError("rejected citations always cause a downgrade")
        return self


class SaferWording(_Contract):
    """A suggested safer wording for part of an UNVERIFIED (NOT_ENOUGH_EVIDENCE) claim
    (softening.py). It only removes or softens words and is **not evidence-backed**: there is no
    evidence for an unverified claim. It is kept apart from ``Correction`` (evidence-backed, only
    on CONTRADICTED claims), labelled as such, and never makes the claim supported."""

    label: Literal["safer_wording"] = "safer_wording"
    evidence_backed: Literal[False] = False
    target_span: SourceSpan  # inside the claim's source_span; offsets into the content text
    original_text: Annotated[str, Field(min_length=1, max_length=4_000)]
    replacement_text: Annotated[str, Field(min_length=1, max_length=4_000)]

    @field_validator("replacement_text")
    @classmethod
    def _single_clean_line(cls, value: str) -> str:
        if "\n" in value or "\r" in value or has_hidden_characters(value):
            raise ValueError("replacement must be one line without hidden or control characters")
        return value


def _conflict_default(data: dict[str, Any]) -> bool:
    """Default for ClaimResult.conflicting_sources, derived from the citation guard."""
    guard = data.get("citation_guard")
    return guard is not None and any(
        r.reason is GuardRejectionReason.CONFLICTING_EVIDENCE for r in guard.rejected
    )


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
    * ``citation_guard``, when present, must agree with the verdict: a downgraded answer is
      NOT_ENOUGH_EVIDENCE, and an accepted answer has the verdict the model gave.
    """

    claim: Claim
    verdict: Verdict
    evidence: Annotated[list[EvidencePassage], Field(max_length=MAX_PASSAGES_PER_CLAIM)] = []
    citations: Annotated[list[Citation], Field(max_length=MAX_PASSAGES_PER_CLAIM)] = []
    correction: Correction | None = None
    error: ProcessingError | None = None
    # Model-generated explanation, for display only. Never evidence; never checked against sources.
    model_rationale: Annotated[str, Field(max_length=MAX_RATIONALE_CHARS)] | None = None
    citation_guard: CitationGuardReport | None = None
    correction_attempt: CorrectionAttempt | None = None
    # Approved references disagree about this claim (the guard found a conflict). The verdict
    # stays NOT_ENOUGH_EVIDENCE; Member 3 maps this flag to verification_status
    # "conflicting_sources". Derived from citation_guard: filled in when omitted, rejected when wrong.
    conflicting_sources: Annotated[bool, Field(strict=True)] = Field(
        default_factory=_conflict_default
    )
    # Optional, NOT_ENOUGH_EVIDENCE only, never evidence-backed (see SaferWording). Never mixed
    # with ``correction``, which is the only source of a suggested correction.
    safer_wording: SaferWording | None = None
    # Both derived from the fields above by fixed rules: filled in when omitted, rejected when they
    # disagree, so neither can be inflated by a caller or a model.
    evidence_strength: EvidenceStrength = Field(default_factory=_strength_default)
    # Why a person must look (EVAL.md Phase 5). Always includes the fixed floor: every verdict
    # except SUPPORTED, and SUPPORTED on weak evidence. A DecisionPolicy may add reasons to a
    # SUPPORTED claim; nothing can remove one.
    review_reasons: list[ClaimReviewReason] = Field(default_factory=_review_reasons_default)
    # True exactly when there is at least one review reason.
    requires_human_review: Annotated[bool, Field(strict=True)] = Field(
        default_factory=_review_needed
    )

    @model_validator(mode="after")
    def _check(self) -> ClaimResult:
        self._check_verdict_shape()
        self._check_guard()
        self._check_correction_attempt()
        _require_unique_passages(self.evidence)
        self._check_citations()
        self._check_correction()
        # Checked last so a structurally wrong result reports its structural error first.
        expected = evidence_strength(
            self.verdict, self.claim.statement, self.evidence, self.citations
        )
        if self.evidence_strength is not expected:
            raise ValueError(
                f"evidence_strength must be {expected.value} for this verdict and evidence"
            )
        reasons = set(self.review_reasons)
        if len(reasons) != len(self.review_reasons):
            raise ValueError("duplicate review reason")
        floor = set(floor_review_reasons(self.verdict, self.evidence_strength))
        if not floor <= reasons:
            raise ValueError(
                "review_reasons must include every floor reason for this verdict and evidence"
            )
        extra = reasons - floor
        if extra & FLOOR_REVIEW_REASONS:
            raise ValueError(
                "a floor review reason that does not apply to this verdict and evidence"
            )
        if extra and self.verdict is not Verdict.SUPPORTED:
            raise ValueError("policy review reasons apply only to SUPPORTED claims")
        if self.requires_human_review is not bool(reasons):
            raise ValueError(
                "requires_human_review must be true exactly when there is a review reason"
            )
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
        if self.safer_wording is not None:
            if verdict is not Verdict.NOT_ENOUGH_EVIDENCE:
                raise ValueError("safer_wording is only allowed on a NOT_ENOUGH_EVIDENCE claim")
            span, target = self.claim.source_span, self.safer_wording.target_span
            if not (span.start <= target.start and target.end <= span.end):
                raise ValueError(
                    "safer_wording.target_span must lie inside the claim's source_span"
                )
        if self.conflicting_sources is not _conflict_default(
            {"citation_guard": self.citation_guard}
        ):
            raise ValueError(
                "conflicting_sources must be true exactly when the guard found conflicting evidence"
            )
        if self.error is not None and self.error.claim_id not in (None, self.claim.claim_id):
            raise ValueError("error.claim_id does not match the claim")

    def _check_guard(self) -> None:
        guard = self.citation_guard
        if guard is None:
            return
        if self.verdict is Verdict.ERROR:
            raise ValueError(
                "an ERROR result has no citation_guard; the model gave no usable answer"
            )
        if guard.downgraded and self.verdict is not Verdict.NOT_ENOUGH_EVIDENCE:
            raise ValueError("a downgraded answer must be NOT_ENOUGH_EVIDENCE")
        if not guard.downgraded and guard.model_verdict is not self.verdict:
            raise ValueError(
                "citation_guard.model_verdict differs from the verdict without a downgrade"
            )

    def _check_citations(self) -> None:
        passages = {p.passage_id: p for p in self.evidence}
        seen: set[tuple[str, int, int]] = set()
        for citation in self.citations:
            passage = passages.get(citation.passage_id)
            if passage is None:
                raise ValueError(
                    f"citation references passage {citation.passage_id} which is not in evidence"
                )
            if (
                citation.doc_id != passage.doc_id
                or citation.doc_text_sha256 != passage.doc_text_sha256
            ):
                raise ValueError(
                    f"citation of {citation.passage_id} names a different document than the passage"
                )
            if not passage.span.contains(citation.quote_span):
                raise ValueError(f"citation quote_span lies outside passage {citation.passage_id}")
            offset = passage.span.start
            excerpt = passage.text[
                citation.quote_span.start - offset : citation.quote_span.end - offset
            ]
            if excerpt != citation.quote:
                raise ValueError(
                    f"citation quote is not the verbatim text of passage {citation.passage_id}"
                )
            key = _citation_key(citation)
            if key in seen:
                raise ValueError(f"duplicate citation of {citation.passage_id}")
            seen.add(key)

    def _check_correction_attempt(self) -> None:
        attempt = self.correction_attempt
        if attempt is not None and self.verdict is not Verdict.CONTRADICTED:
            raise ValueError("a correction is only attempted for a CONTRADICTED claim")
        proposed = attempt is not None and attempt.status is CorrectionStatus.PROPOSED
        if self.correction is not None and not proposed:
            raise ValueError("a correction requires a correction_attempt with status PROPOSED")
        if proposed and self.correction is None:
            raise ValueError("a PROPOSED correction_attempt requires the correction")

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


class EvidenceCoverage(_Contract):
    """Share of checked claims backed by validated evidence: supported / checked.

    ``checked`` counts claims with a SUPPORTED, CONTRADICTED or NOT_ENOUGH_EVIDENCE verdict;
    ERROR results are not checked and are counted separately. ``value`` is null when nothing was
    checked, never 0% or 100%.
    """

    supported: Annotated[int, Field(strict=True, ge=0)]
    checked: Annotated[int, Field(strict=True, ge=0)]
    value: float | None = None  # omitted means null; still must equal supported / checked

    @model_validator(mode="after")
    def _check(self) -> EvidenceCoverage:
        if self.supported > self.checked:
            raise ValueError("supported cannot exceed checked")
        expected = self.supported / self.checked if self.checked else None
        if self.value != expected:
            raise ValueError("value must equal supported / checked (null when checked is 0)")
        return self


class ReviewReason(str, Enum):
    CONTRADICTED_CLAIMS = "contradicted_claims"
    UNVERIFIED_CLAIMS = "unverified_claims"  # NOT_ENOUGH_EVIDENCE
    PROCESSING_ERRORS = "processing_errors"  # ERROR results or request-level errors
    CITATIONS_REJECTED = "citations_rejected"  # the guard downgraded at least one answer
    CORRECTIONS_NEED_REVIEW = "corrections_need_review"  # a correction could not be proposed safely
    WEAK_EVIDENCE = "weak_evidence"  # a SUPPORTED claim rests only on weak evidence
    CONFLICTING_EVIDENCE = "conflicting_evidence"  # the references disagree about a claim's figure
    POLICY_THRESHOLD = (
        "policy_threshold"  # the decision policy routed a SUPPORTED claim (EVAL.md Phase 5)
    )
    RULE_VIOLATIONS = "rule_violations"  # an explicit brand rule was broken (rules.py)


class ReportScore(_Contract):
    """The engine-side score of a report: counts, evidence coverage and review routing.

    Deliberately not a confidence or quality score. Each number answers one question about the
    verdicts and nothing else; retrieval scores stay on passages and citation outcomes stay on
    each result's citation_guard. No thresholds are applied: ``requires_human_review`` is true
    whenever any reason applies.
    """

    claims: Annotated[int, Field(strict=True, ge=0)]
    supported: Annotated[int, Field(strict=True, ge=0)]
    contradicted: Annotated[int, Field(strict=True, ge=0)]
    not_enough_evidence: Annotated[int, Field(strict=True, ge=0)]
    errors: Annotated[int, Field(strict=True, ge=0)]
    evidence_coverage: EvidenceCoverage
    citations_rejected: Annotated[int, Field(strict=True, ge=0)]
    corrections_proposed: Annotated[int, Field(strict=True, ge=0)]
    corrections_need_review: Annotated[int, Field(strict=True, ge=0)]
    requires_human_review: Annotated[bool, Field(strict=True)]
    review_reasons: list[ReviewReason]
    rule_violations: Annotated[int, Field(strict=True, ge=0)] = 0

    @classmethod
    def compute(
        cls,
        results: list[ClaimResult],
        report_errors: list[ProcessingError],
        rule_findings: list[RuleFinding] = (),
    ) -> ReportScore:
        counts = Counter(r.verdict for r in results)
        attempts = [r.correction_attempt for r in results if r.correction_attempt is not None]
        proposed = sum(a.status is CorrectionStatus.PROPOSED for a in attempts)
        need_review = len(attempts) - proposed
        rejected = sum(
            1 for r in results if r.citation_guard is not None and r.citation_guard.downgraded
        )
        errors = counts[Verdict.ERROR]
        checked = len(results) - errors
        reasons = [
            reason
            for reason, applies in (
                (ReviewReason.CONTRADICTED_CLAIMS, counts[Verdict.CONTRADICTED] > 0),
                (ReviewReason.UNVERIFIED_CLAIMS, counts[Verdict.NOT_ENOUGH_EVIDENCE] > 0),
                (ReviewReason.PROCESSING_ERRORS, errors > 0 or bool(report_errors)),
                (ReviewReason.CITATIONS_REJECTED, rejected > 0),
                (ReviewReason.CORRECTIONS_NEED_REVIEW, need_review > 0),
                (
                    ReviewReason.WEAK_EVIDENCE,
                    any(
                        r.verdict is Verdict.SUPPORTED
                        and r.evidence_strength is EvidenceStrength.WEAK
                        for r in results
                    ),
                ),
                (
                    ReviewReason.CONFLICTING_EVIDENCE,
                    any(
                        r.citation_guard is not None
                        and any(
                            x.reason is GuardRejectionReason.CONFLICTING_EVIDENCE
                            for x in r.citation_guard.rejected
                        )
                        for r in results
                    ),
                ),
                (ReviewReason.RULE_VIOLATIONS, bool(rule_findings)),
                (
                    ReviewReason.POLICY_THRESHOLD,
                    any(set(r.review_reasons) - FLOOR_REVIEW_REASONS for r in results),
                ),
            )
            if applies
        ]
        return cls(
            claims=len(results),
            supported=counts[Verdict.SUPPORTED],
            contradicted=counts[Verdict.CONTRADICTED],
            not_enough_evidence=counts[Verdict.NOT_ENOUGH_EVIDENCE],
            errors=errors,
            evidence_coverage=EvidenceCoverage(
                supported=counts[Verdict.SUPPORTED],
                checked=checked,
                value=counts[Verdict.SUPPORTED] / checked if checked else None,
            ),
            citations_rejected=rejected,
            corrections_proposed=proposed,
            corrections_need_review=need_review,
            requires_human_review=bool(reasons),
            review_reasons=reasons,
            rule_violations=len(rule_findings),
        )


class EngineProvenance(_Contract):
    """What produced a report, so results can be reproduced and compared across versions."""

    engine_version: Label
    contract_version: ContractVersion = CONTRACT_VERSION
    retrieval_method: RetrievalMethod
    provider: Label | None = None  # the LLMProvider's name, e.g. "openrouter"
    model_id: Label | None = None
    prompt_versions: dict[Label, Label] = {}


class VerificationReport(_Contract):
    """What the engine returns for one VerificationRequest."""

    contract_version: ContractVersion = CONTRACT_VERSION
    request_id: RequestId
    tenant_id: TenantId
    reference_set_id: ReferenceSetId | None = None  # the request's, echoed unchanged
    content_sha256: Sha256Hex
    content_length: Annotated[int, Field(strict=True, ge=1, le=MAX_CONTENT_CHARS)]
    references: Annotated[
        list[ReferenceDescriptor], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)
    ]
    status: ReportStatus
    results: Annotated[list[ClaimResult], Field(max_length=MAX_CLAIMS)] = []
    # Violations of the request's explicit brand rules (rules.py), found before extraction.
    rule_findings: Annotated[list[RuleFinding], Field(max_length=MAX_RULE_FINDINGS)] = []
    errors: list[ProcessingError] = []
    provenance: EngineProvenance
    # Optional so earlier payloads stay valid; when present it must equal ReportScore.compute().
    score: ReportScore | None = None

    @model_validator(mode="after")
    def _check(self) -> VerificationReport:
        self._check_status()
        self._check_claims()
        self._check_provenance()
        if self.score is not None and self.score != ReportScore.compute(
            self.results, self.errors, self.rule_findings
        ):
            raise ValueError(
                "score does not match the results; compute it with ReportScore.compute"
            )
        ids = Counter(f.finding_id for f in self.rule_findings)
        if any(n > 1 for n in ids.values()):
            raise ValueError("duplicate rule finding_id")
        for finding in self.rule_findings:
            if finding.span is not None and not finding.span.fits(self.content_length):
                raise ValueError(f"rule finding {finding.finding_id} span exceeds content_length")
            if any(
                e.source_id not in {r.doc_id for r in self.references} for e in finding.evidence
            ):
                raise ValueError(
                    f"rule finding {finding.finding_id} cites a document not in references"
                )
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
                raise ValueError(
                    f"claim {result.claim.claim_id} source_span exceeds content_length"
                )

    def _check_provenance(self) -> None:
        known = {(r.doc_id, r.text_sha256) for r in self.references}
        if len({doc_id for doc_id, _ in known}) != len(self.references):
            raise ValueError("duplicate reference doc_id")
        for result in self.results:
            for passage in result.evidence:
                if (passage.doc_id, passage.doc_text_sha256) not in known:
                    raise ValueError(
                        f"passage {passage.passage_id} comes from a document not in references"
                    )
                if (
                    passage.reference_set_id is not None
                    and passage.reference_set_id != self.reference_set_id
                ):
                    raise ValueError(
                        f"passage {passage.passage_id} comes from another reference set"
                    )

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
    CONFLICTING_EVIDENCE = "conflicting_evidence"  # references disagree with each other
    # Dataset v2 (EVAL.md Phase 2):
    NEAR_MISS = "near_miss"  # a figure close to the referenced one (5.3 g vs 5.2 g)
    UNIT_MISMATCH = "unit_mismatch"  # the right number with the wrong unit (340 kg vs 340 g)
    OUTDATED_FACT = "outdated_fact"  # a value a newer reference explicitly replaces


class EvalRecord(_Contract):
    """One labelled example for the claim-verification evaluation set (one JSONL line).

    Labels only: an EvalRecord never carries a prediction, and a prediction never carries a label.
    """

    record_id: RecordId
    split: EvalSplit = EvalSplit.DEV
    claim_text: ClaimText
    references: Annotated[
        list[ReferenceDocument], Field(min_length=1, max_length=MAX_REFERENCE_DOCS)
    ]
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
                raise ValueError(
                    f"gold_evidence quote is not the text at its span in {gold.doc_id}"
                )
        return self
