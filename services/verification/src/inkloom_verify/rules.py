"""Deterministic terminology, brand-compliance and accessibility checks (no model call).

Two entry points:

* ``evaluate_rules(text, rules, metadata)`` (for the backend, see RULES_HANDOFF.md): validates its
  input, runs every rule, and returns a ``RuleEvaluation`` with the findings and one ``RuleCheck``
  per rule (passed / violated / not_checkable / error), so a check that could not run is never
  reported as clean. Accessibility checks run with their defaults unless ``rules.style`` sets them
  or ``accessibility_defaults=False``.
* ``check_rules(text, rules)`` (the engine pipeline, ``VerificationRequest.rules``): the findings
  only, with accessibility checks only when ``rules.style`` is set, as before.

Terminology (category "terminology"):

* ``required_term``: the term must appear (one document-level finding when it does not);
* ``prohibited_term``: every occurrence is flagged; ``approved_alternative`` is the suggestion;
* ``product_naming``: every case-insensitive occurrence of the approved name or a listed variant
  not written exactly as approved is flagged; the approved name is the suggestion;
* ``preferred_term`` / ``spelling``: every discouraged / incorrect form is flagged with the
  preferred / correct one as the suggestion;
* ``terminology_consistency``: when a document uses more than one of a rule's accepted forms, the
  less frequent forms are flagged (no suggestion: none of them is wrong).

Matching (``term_pattern``): literal, never a regular expression from configuration;
case-insensitive and whole-word by default (``case_sensitive``, ``whole_word`` per rule); runs of
whitespace (including non-breaking spaces), straight/curly apostrophes and hyphen/dash variants
match each other; text and terms are compared in Unicode NFC with offsets mapped back to the
original text. Every occurrence is reported, longest form first, never two findings of one rule
on overlapping text. Different rules may flag the same text (each finding names its rule).

Brand compliance (category "brand_compliance"): ``required_disclaimer`` (whitespace and case
ignored; always, or when a trigger term appears) and ``numeric_limit`` (a figure with one of the
rule's units, in a sentence mentioning the subject, within the rule's range).

Accessibility (category "accessibility"; ``StyleRules``; Markdown, simple HTML and optional
``ContentMetadata``):

* ``all_caps_run``, ``emoji_run``: always checkable on the text;
* ``vague_link_text``: link text such as "click here", plus bare "click here" in plain text;
  not_checkable when the text has no links;
* ``missing_alt_text``: ``![](x)``, ``<img>`` without ``alt``, metadata images with alt_text None
  (``alt=""`` / ``""`` is decorative and not flagged); not_checkable with no images anywhere;
* ``heading_structure``: Markdown/HTML headings: empty, skipped levels (h2 -> h4), a second H1;
  not_checkable with no headings;
* ``missing_captions``: ``<video>`` without a captions/subtitles ``<track>``, metadata video with
  captions False, metadata audio with transcript False; embedded players (iframe/embed/object),
  ``<audio>`` and metadata marked unknown cannot be inspected;
* ``low_contrast``: inline ``style`` colour + background pairs and metadata colour pairs, against
  the WCAG ratio (4.5, 3 for large text); not_checkable when no pair with parseable colours exists.

Each finding is a ``RuleFinding`` (shared finding shape: check_type "rule", verification_status
"not_applicable", requires_human_review true). Submitted text is untrusted data: it is matched,
never interpreted, and no finding, check reason or log line repeats more than the matched text.
Every pattern applied to submitted text is linear or bounded in length.

Known limits: no stemming or synonyms ("guaranteed" does not match "guarantee"); sentence splitting
is punctuation-based; numeric rules read digits next to a unit only; the accessibility checks read
markup in the submitted text and the metadata given, they do not render pages, read uploaded files
or judge reading level; emoji are recognised by Unicode block.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from bisect import bisect_left
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from inkloom_verify.schemas import (
    MAX_CONTENT_CHARS,
    MAX_RULE_FINDINGS,
    MAX_RULE_TEXT_CHARS,
    RULE_CATEGORY,
    BrandRules,
    ConsistencyRule,
    ContentMetadata,
    NumericLimitRule,
    PreferredTermRule,
    ProductNamingRule,
    RuleCheck,
    RuleCheckStatus,
    RuleEvaluation,
    RuleEvidence,
    RuleFinding,
    RuleType,
    SourceSpan,
    SpellingRule,
    StyleRules,
    _MatchOptions,
    _Rule,
)

logger = logging.getLogger(__name__)


class RuleEvaluationError(ValueError):
    """The rules or the content could not be used; nothing was evaluated. ``problems`` names
    fields and reasons only, never the submitted text or a configured value."""

    def __init__(self, message: str, problems: list[str] | None = None) -> None:
        super().__init__(message)
        self.problems = problems or []


class RuleConfigurationError(RuleEvaluationError):
    """Malformed or contradictory rules or metadata. Refused rather than partly applied."""


class RuleInputError(RuleEvaluationError):
    """The content is not a non-blank string within the size limit."""


class _NotCheckable(Exception):
    """Raised by a check whose input data is missing; the message is the (content-free) reason."""


# --- Text and matching ----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Text:
    """The submitted text in NFC, with each NFC position mapped back to the original text."""

    original: str
    norm: str
    starts: list[int]
    ends: list[int]

    def span(self, start: int, end: int) -> tuple[int, int]:
        return self.starts[start], self.ends[end - 1]


def _prepare(text: str) -> _Text:
    if unicodedata.is_normalized("NFC", text):
        n = len(text)
        return _Text(text, text, list(range(n)), list(range(1, n + 1)))
    norm: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        for ch in unicodedata.normalize("NFC", text[i:j]):
            norm.append(ch)
            starts.append(i)
            ends.append(j)
        i = j
    return _Text(text, "".join(norm), starts, ends)


_APOSTROPHES = "'’ʼ‘`"
_HYPHENS = "-‐‑‒–—"


def _char_class(ch: str) -> str:
    if ch in _APOSTROPHES:
        return "[" + re.escape(_APOSTROPHES) + "]"
    if ch in _HYPHENS:
        return "[" + re.escape(_HYPHENS) + "]"
    return re.escape(ch)


def term_pattern(term: str, case_sensitive: bool = False, whole_word: bool = True) -> re.Pattern[str]:
    """A literal pattern for ``term`` (never a regular expression from configuration)."""
    term = unicodedata.normalize("NFC", term.strip())
    body = r"\s+".join("".join(_char_class(c) for c in part) for part in term.split())
    start = r"(?<!\w)" if whole_word and term[:1].isalnum() else ""
    end = r"(?!\w)" if whole_word and term[-1:].isalnum() else ""
    return re.compile(start + body + end, 0 if case_sensitive else re.IGNORECASE)


@dataclass
class _Hit:
    """One violation before it becomes a RuleFinding. ``start``/``end`` are original offsets;
    None for a document-level finding."""

    explanation: str
    start: int | None = None
    end: int | None = None
    correction: str | None = None


@dataclass
class _Match:
    start: int
    end: int
    text: str


def _find(t: _Text, term: str, opts: _MatchOptions | None = None) -> list[_Match]:
    case_sensitive = opts.case_sensitive if opts else False
    whole_word = opts.whole_word if opts else True
    found = []
    for m in term_pattern(term, case_sensitive, whole_word).finditer(t.norm):
        s, e = t.span(m.start(), m.end())
        found.append(_Match(s, e, t.original[s:e]))
    return found


def _find_all(t: _Text, terms: list[str], opts: _MatchOptions | None = None) -> list[tuple[str, _Match]]:
    """Every occurrence of any of ``terms``, longest term first, never overlapping."""
    taken: list[tuple[int, int]] = []
    out = []
    for term in sorted(terms, key=len, reverse=True):
        for m in _find(t, term, opts):
            if any(m.start < e and s < m.end for s, e in taken):
                continue
            taken.append((m.start, m.end))
            out.append((term, m))
    return sorted(out, key=lambda pair: pair[1].start)


def _normalised(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _clip(text: str, limit: int = MAX_RULE_TEXT_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- The runner ---------------------------------------------------------------------------------------


@dataclass
class _Run:
    t: _Text
    findings: list[RuleFinding] = field(default_factory=list)
    checks: list[RuleCheck] = field(default_factory=list)
    total: int = 0

    def anchor(self) -> tuple[int, int]:
        """The content's first non-blank line, clipped: where a document-level finding points."""
        text = self.t.original
        for m in re.finditer(r"[^\n]+", text):
            line = m.group(0)
            lead = len(line) - len(line.lstrip())
            stripped = line.strip()
            if stripped:
                start = m.start() + lead
                return start, start + min(len(stripped), MAX_RULE_TEXT_CHARS)
        return 0, min(len(text), MAX_RULE_TEXT_CHARS)

    def run(self, rule: _Rule, rule_type: RuleType, check: Callable[[], list[_Hit]], basis: str | None = None) -> None:
        try:
            hits = check()
        except _NotCheckable as reason:
            self._record(rule, rule_type, RuleCheckStatus.NOT_CHECKABLE, 0, str(reason))
            return
        except Exception as error:  # noqa: BLE001 - one broken rule must not stop or pass the others
            logger.error("rules: %s (%s) failed: %s", rule.rule_id, rule_type.value, type(error).__name__)
            self._record(rule, rule_type, RuleCheckStatus.ERROR, 0, f"the check could not run ({type(error).__name__})")
            return
        for n, hit in enumerate(hits, start=1):
            self.total += 1
            if len(self.findings) < MAX_RULE_FINDINGS:
                self.findings.append(self._finding(rule, rule_type, hit, n, basis))
        self._record(rule, rule_type, RuleCheckStatus.VIOLATED if hits else RuleCheckStatus.PASSED, len(hits))

    def _record(self, rule: _Rule, rule_type: RuleType, status: RuleCheckStatus, n: int, reason: str | None = None) -> None:
        self.checks.append(RuleCheck(rule_id=rule.rule_id, rule_type=rule_type, category=RULE_CATEGORY[rule_type],
                                     status=status, findings=n, reason=reason))

    def _finding(self, rule: _Rule, rule_type: RuleType, hit: _Hit, n: int, basis: str | None) -> RuleFinding:
        evidence = [RuleEvidence(source_id=rule.source.doc_id, quote=rule.source.quote)] if rule.source else []
        if hit.start is None:
            scope, (start, end) = "document", self.anchor()
        else:
            # A match longer than the field limit (a long shouted paragraph) is cut at the limit,
            # so the finding stays valid instead of failing the whole evaluation.
            scope, start, end = "text", hit.start, min(hit.end, hit.start + MAX_RULE_TEXT_CHARS)
        correction = hit.correction if scope == "text" and end == hit.end else None
        return RuleFinding(
            finding_id=f"rul_{rule.rule_id}_{n}",
            rule_id=rule.rule_id,
            rule_type=rule_type,
            category=RULE_CATEGORY[rule_type],
            severity=rule.severity,
            scope=scope,
            original_text=self.t.original[start:end],
            span=SourceSpan(start=start, end=end),
            explanation=_clip(hit.explanation),
            source_ids=[e.source_id for e in evidence],
            evidence=evidence,
            suggested_correction=correction,
            suggestion_basis=(("approved_document" if evidence else basis) if correction else None),
        )


# --- Entry points -------------------------------------------------------------------------------------


def _problems(error: ValidationError) -> list[str]:
    """Field paths and messages only: pydantic's error input (a configured value or content) is dropped."""
    return [(".".join(str(p) for p in e["loc"]) or "rules") + ": " + e["msg"] for e in error.errors()][:20]


def evaluate_rules(
    text: str,
    rules: BrandRules | Mapping[str, Any] | None = None,
    metadata: ContentMetadata | Mapping[str, Any] | None = None,
    *,
    accessibility_defaults: bool = True,
) -> RuleEvaluation:
    """Runs every rule on ``text``. Raises RuleConfigurationError / RuleInputError (nothing run)
    for malformed rules, metadata or content; never returns a partial evaluation silently."""
    if not isinstance(text, str) or not text.strip():
        raise RuleInputError("content must be non-blank text")
    if len(text) > MAX_CONTENT_CHARS:
        raise RuleInputError(f"content exceeds {MAX_CONTENT_CHARS} characters")
    try:
        brand = rules if isinstance(rules, BrandRules) or rules is None else BrandRules.model_validate(rules)
    except ValidationError as error:
        raise RuleConfigurationError("invalid brand rules", _problems(error)) from None
    try:
        meta = metadata if isinstance(metadata, ContentMetadata) or metadata is None else ContentMetadata.model_validate(metadata)
    except ValidationError as error:
        raise RuleConfigurationError("invalid content metadata", _problems(error)) from None

    run = _Run(_prepare(text))
    if brand is not None:
        _brand_checks(run, brand)
    style = brand.style if brand is not None and brand.style is not None else (StyleRules() if accessibility_defaults else None)
    if style is not None:
        _style_checks(run, style, meta or ContentMetadata())
    if run.total > MAX_RULE_FINDINGS:
        logger.info("rules: %d findings, only the first %d kept", run.total, MAX_RULE_FINDINGS)
    return RuleEvaluation(findings=run.findings, checks=run.checks,
                          complete=not any(c.status is RuleCheckStatus.ERROR for c in run.checks),
                          truncated=run.total > len(run.findings))


def check_rules(text: str, rules: BrandRules | None) -> list[RuleFinding]:
    """The engine pipeline's view: findings for ``rules`` (style checks only if rules.style is set)."""
    if rules is None:
        return []
    return evaluate_rules(text, rules, accessibility_defaults=False).findings


# --- Terminology and brand compliance -------------------------------------------------------------


def _brand_checks(run: _Run, rules: BrandRules) -> None:
    t = run.t
    for rule in rules.required_terms:
        run.run(rule, RuleType.REQUIRED_TERM, lambda r=rule: [] if _find(t, r.term, r) else [
            _Hit(f'The required term "{r.term}" does not appear.')])
    for rule in rules.prohibited_terms:
        run.run(rule, RuleType.PROHIBITED_TERM, lambda r=rule: [
            _Hit(f'"{m.text}" is a prohibited term.', m.start, m.end, r.approved_alternative)
            for m in _find(t, r.term, r)], basis="brand_rule")
    for rule in rules.product_names:
        run.run(rule, RuleType.PRODUCT_NAMING, lambda r=rule: _naming(t, r), basis="brand_rule")
    for rule in rules.preferred_terms:
        run.run(rule, RuleType.PREFERRED_TERM, lambda r=rule: _replace(t, r, r.discouraged, r.preferred,
                                                                        'Use "{want}" instead of "{got}".'), basis="brand_rule")
    for rule in rules.spelling:
        run.run(rule, RuleType.SPELLING, lambda r=rule: _replace(t, r, r.incorrect, r.correct,
                                                                  'The brand spells this "{want}", not "{got}".'), basis="brand_rule")
    for rule in rules.consistency:
        run.run(rule, RuleType.TERMINOLOGY_CONSISTENCY, lambda r=rule: _consistency(t, r))
    content = _normalised(t.original)
    for rule in rules.disclaimers:
        def disclaimer(r=rule) -> list[_Hit]:
            triggered = not r.trigger_terms or any(_find(t, term) for term in r.trigger_terms)
            missing = triggered and _normalised(r.disclaimer) not in content
            return [_Hit(f'The required disclaimer "{r.disclaimer}" is missing.')] if missing else []
        run.run(rule, RuleType.REQUIRED_DISCLAIMER, disclaimer)
    for rule in rules.numeric_limits:
        run.run(rule, RuleType.NUMERIC_LIMIT, lambda r=rule: _numeric(t.original, r))


def _replace(t: _Text, rule: PreferredTermRule | SpellingRule, unwanted: list[str], wanted: str, template: str) -> list[_Hit]:
    return [_Hit(template.format(want=wanted, got=m.text), m.start, m.end, wanted)
            for _, m in _find_all(t, unwanted, rule)]


def _naming(t: _Text, rule: ProductNamingRule) -> list[_Hit]:
    return [_Hit(f'"{m.text}" is not the approved product name "{rule.approved_name}".', m.start, m.end, rule.approved_name)
            for _, m in _find_all(t, [rule.approved_name, *rule.variants]) if m.text != rule.approved_name]


def _consistency(t: _Text, rule: ConsistencyRule) -> list[_Hit]:
    found = _find_all(t, list(rule.variants), rule)
    used: dict[str, list[_Match]] = {}
    for term, m in found:
        used.setdefault(term, []).append(m)
    if len(used) < 2:
        return []
    # The most frequent form stays; ties go to the form used first.
    keep = max(used, key=lambda term: (len(used[term]), -used[term][0].start))
    summary = ", ".join(f'"{term}" ({len(ms)})' for term, ms in sorted(used.items(), key=lambda kv: kv[1][0].start))
    return [_Hit(f'This document mixes {summary}. Use one form throughout (most used here: "{keep}").', m.start, m.end)
            for term, ms in used.items() if term != keep for m in ms]


_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_NUMBER = r"(\d+(?:[.,]\d+)*)"


def _numeric(text: str, rule: NumericLimitRule) -> list[_Hit]:
    units = "|".join(re.escape(u) for u in sorted(rule.units, key=len, reverse=True))
    figure = re.compile(_NUMBER + r"\s*(?:" + units + r")(?![\w])", re.IGNORECASE)
    subject = term_pattern(rule.subject)
    low, high = rule.minimum, rule.maximum
    limit = (f"between {low:g} and {high:g}" if low is not None and high is not None
             else f"at most {high:g}" if high is not None else f"at least {low:g}")
    hits = []
    for sentence in _SENTENCE.finditer(text):
        if not subject.search(sentence.group(0)):
            continue
        for match in figure.finditer(text, sentence.start(), sentence.end()):
            number = match.group(1)
            # "1,200" is twelve hundred; "4,5" (one to two digits after the comma) is a decimal comma.
            value = float(number.replace(",", "") if re.search(r",\d{3}(?!\d)", number) else number.replace(",", "."))
            if (low is not None and value < low) or (high is not None and value > high):
                hits.append(_Hit(f'"{match.group(0)}" for {rule.subject} breaks the rule: it must be {limit}.',
                                 match.start(), match.end()))
    return hits


# --- Accessibility and tone ---------------------------------------------------------------------------

STYLE_RULE_IDS = {
    RuleType.ALL_CAPS_RUN: "style.all_caps",
    RuleType.EMOJI_RUN: "style.emoji",
    RuleType.VAGUE_LINK_TEXT: "style.link_text",
    RuleType.MISSING_ALT_TEXT: "style.alt_text",
    RuleType.HEADING_STRUCTURE: "style.headings",
    RuleType.MISSING_CAPTIONS: "style.media_captions",
    RuleType.LOW_CONTRAST: "style.contrast",
}
BARE_VAGUE_PHRASES = ("click here",)  # flagged in plain text too, not only as link text

_WORD = re.compile(r"[^\W\d_][\w'’-]*")
_EMOJI_BASE = (r"[\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F1FF\U0001F200-\U0001F2FF"
               r"\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F"
               r"\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
               r"☀-➿⬀-⯿⌀-⏿]")
_EMOJI_MODIFIER = r"[︎️\U0001F3FB-\U0001F3FF⃣]"
_ONE_EMOJI = _EMOJI_BASE + _EMOJI_MODIFIER + "*(?:‍" + _EMOJI_BASE + _EMOJI_MODIFIER + "*)*"
_EMOJI_RUN = re.compile("(?:" + _ONE_EMOJI + ")(?:[ \t]*(?:" + _ONE_EMOJI + "))*")
_ONE_EMOJI_RE = re.compile(_ONE_EMOJI)
# Patterns on submitted text must stay linear even on hostile markup (100 000 characters of
# unclosed tags or brackets): a tag is scanned only up to the next "<" ([^<>]), link and image text
# only up to the next "[", and an element's closing tag is found by binary search over the closing
# tags' positions (_elements), never by scanning forward from every opening tag.
_MD_LINK = re.compile(r"(?<!!)\[([^\[\]\n]{1,500})\]\(([^()\s]{0,2000})[^()\n]{0,500}\)")
_MD_IMAGE = re.compile(r"!\[([^\[\]\n]{0,500})\]\(([^()\n]{0,2000})\)")
_HTML_IMG = re.compile(r"<img\b[^<>]{0,2000}>", re.IGNORECASE)
_ALT_ATTR = re.compile(r"\balt\s*=", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]{0,2000}>")
_MD_HEADING = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+([^\n]{0,500}?))?[ \t#]*$", re.MULTILINE)
_CAPTION_TRACK = re.compile(r"<track\b[^<>]{0,2000}\bkind\s*=\s*[\"']?(captions|subtitles)\b", re.IGNORECASE)
_AUDIO = re.compile(r"<audio\b[^<>]{0,2000}>", re.IGNORECASE)
_EMBED = re.compile(r"<(iframe|embed|object)\b[^<>]{0,2000}>", re.IGNORECASE)
_ANY_TAG = re.compile(r"<[a-zA-Z][a-zA-Z0-9]{0,20}\b[^<>]{0,3000}>")
_STYLE_ATTR = re.compile(r"\bstyle\s*=\s*(\"([^\"]{0,1000})\"|'([^']{0,1000})')", re.IGNORECASE)


@dataclass
class _Element:
    open_start: int
    open_end: int
    inner_end: int | None  # None: self-closing, or no closing tag within reach
    close_end: int | None
    open_text: str


def _elements(text: str, tag: str, max_inner: int = 20_000) -> list[_Element]:
    """Opening ``<tag ...>`` elements with their closing ``</tag>`` (the next one after the opening
    tag, at most ``max_inner`` characters later), found in O(n log n)."""
    opens = re.compile(rf"<{tag}\b[^<>]{{0,2000}}>", re.IGNORECASE)
    closes = [(m.start(), m.end()) for m in re.finditer(rf"</{tag}\s*>", text, re.IGNORECASE)]
    starts = [c[0] for c in closes]
    found = []
    for m in opens.finditer(text):
        close = None
        if not m.group(0).endswith("/>"):
            i = bisect_left(starts, m.end())
            if i < len(starts) and starts[i] - m.end() <= max_inner:
                close = closes[i]
        found.append(_Element(m.start(), m.end(), close[0] if close else None, close[1] if close else None, m.group(0)))
    return found


_CSS_COLOR = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]{1,100})", re.IGNORECASE)
_CSS_BACKGROUND = re.compile(r"(?:^|;)\s*background(?:-color)?\s*:\s*([^;]{1,100})", re.IGNORECASE)


def _style_checks(run: _Run, style: StyleRules, meta: ContentMetadata) -> None:
    text = run.t.original

    def rule(rule_type: RuleType) -> _Rule:
        return _Rule(rule_id=STYLE_RULE_IDS[rule_type], severity=style.severity)

    if style.all_caps:
        allowed = {a.casefold() for a in style.allowed_caps}
        run.run(rule(RuleType.ALL_CAPS_RUN), RuleType.ALL_CAPS_RUN, lambda: [
            _Hit(f"{n} words in a row are in capitals; screen readers may spell them out and readers read it as shouting.",
                 s, e) for s, e, n in _caps_runs(text, style.all_caps_min_words, allowed)])
    if style.emoji:
        def emoji() -> list[_Hit]:
            hits = []
            for m in _EMOJI_RUN.finditer(text):
                n = len(_ONE_EMOJI_RE.findall(m.group(0)))
                if n > style.emoji_max_run:
                    hits.append(_Hit(f"{n} emoji in a row (at most {style.emoji_max_run}); screen readers read every one aloud.",
                                     m.start(), m.end()))
            return hits
        run.run(rule(RuleType.EMOJI_RUN), RuleType.EMOJI_RUN, emoji)
    if style.vague_link_text:
        run.run(rule(RuleType.VAGUE_LINK_TEXT), RuleType.VAGUE_LINK_TEXT, lambda: _vague_links(run.t, style))
    if style.alt_text:
        run.run(rule(RuleType.MISSING_ALT_TEXT), RuleType.MISSING_ALT_TEXT, lambda: _alt_text(text, meta))
    if style.heading_structure:
        run.run(rule(RuleType.HEADING_STRUCTURE), RuleType.HEADING_STRUCTURE, lambda: _headings(text))
    if style.media_captions:
        run.run(rule(RuleType.MISSING_CAPTIONS), RuleType.MISSING_CAPTIONS, lambda: _captions(text, meta))
    if style.color_contrast:
        run.run(rule(RuleType.LOW_CONTRAST), RuleType.LOW_CONTRAST, lambda: _contrast(text, meta, style))


def _caps_runs(text: str, min_words: int, allowed: set[str]) -> Iterator[tuple[int, int, int]]:
    """(start, end, words) of upper-case runs (2+ letters per word) on one line; allowed words skipped."""
    run: list[re.Match[str]] = []

    def flush() -> Iterator[tuple[int, int, int]]:
        if len(run) >= min_words:
            yield run[0].start(), run[-1].end(), len(run)

    previous_end = 0
    for word in _WORD.finditer(text):
        token = word.group(0)
        letters = [c for c in token if c.isalpha()]
        if run and "\n" in text[previous_end:word.start()]:
            yield from flush()
            run = []
        previous_end = word.end()
        if token.casefold() in allowed or token.strip("'’-").casefold() in allowed:
            continue
        if len(letters) >= 2 and all(c.isupper() for c in letters):
            run.append(word)
        else:
            yield from flush()
            run = []
    yield from flush()


def _vague_links(t: _Text, style: StyleRules) -> list[_Hit]:
    text = t.original
    vague = {" ".join(p.split()).casefold() for p in style.vague_link_phrases}
    links = [(m.start(1), m.end(1)) for m in _MD_LINK.finditer(text)]
    links += [(e.open_end, e.inner_end) for e in _elements(text, "a", 2_000)
              if e.inner_end is not None and text[e.open_end:e.inner_end].strip()]
    hits, flagged = [], []
    for start, end in sorted(links):
        label = " ".join(_TAG.sub(" ", text[start:end]).split()).casefold().strip(" .:!")
        if label in vague:
            flagged.append((start, end))
            hits.append(_Hit(f'Link text "{text[start:end].strip()}" does not say where the link goes.', start, end))
    bare = [m for phrase in BARE_VAGUE_PHRASES for m in _find(t, phrase)
            if not any(m.start < e and s < m.end for s, e in flagged)]
    hits += [_Hit(f'"{m.text}" does not say what happens; name the destination or action.', m.start, m.end) for m in bare]
    if not links and not bare:
        raise _NotCheckable("no links in the submitted text")
    return sorted(hits, key=lambda h: h.start)


def _alt_text(text: str, meta: ContentMetadata) -> list[_Hit]:
    md = list(_MD_IMAGE.finditer(text))
    html = list(_HTML_IMG.finditer(text))
    if not md and not html and not meta.images:
        raise _NotCheckable("no images in the submitted text or metadata (images inside uploaded files are not visible here)")
    hits = [_Hit("This image has no alt text, so screen-reader users get nothing from it.", m.start(), m.end())
            for m in md if not m.group(1).strip()]
    hits += [_Hit('This <img> has no alt attribute. Describe the image, or use alt="" if it is decorative.', m.start(), m.end())
             for m in html if not _ALT_ATTR.search(m.group(0))]
    hits += [_Hit(f'Image "{image.ref}" has no alt text (from metadata).') for image in meta.images if image.alt_text is None]
    return hits


def _headings(text: str) -> list[_Hit]:
    found = [(m.start(), m.end(), len(m.group(1)), (m.group(2) or "").strip()) for m in _MD_HEADING.finditer(text)]
    for level in range(1, 7):
        for e in _elements(text, f"h{level}", 2_000):
            if e.inner_end is not None:
                label = " ".join(_TAG.sub(" ", text[e.open_end:e.inner_end]).split())
                found.append((e.open_start, e.close_end, level, label))
    if not found:
        raise _NotCheckable("no headings in the submitted text (Markdown # or HTML <h1>-<h6>)")
    hits, previous, h1_seen = [], None, False
    for start, end, level, label in sorted(found):
        if not label:
            hits.append(_Hit(f"An empty level-{level} heading; screen-reader users navigate by headings.", start, end))
        if previous is not None and level > previous + 1:
            hits.append(_Hit(f"Heading level jumps from {previous} to {level}; use level {previous + 1} first.", start, end))
        if level == 1 and h1_seen:
            hits.append(_Hit("A second level-1 heading; a page should have one main heading.", start, end))
        h1_seen = h1_seen or level == 1
        previous = level
    return hits


def _captions(text: str, meta: ContentMetadata) -> list[_Hit]:
    videos = _elements(text, "video")
    audio = list(_AUDIO.finditer(text))
    embeds = list(_EMBED.finditer(text))
    if not videos and not audio and not embeds and not meta.media:
        raise _NotCheckable("no video or audio in the submitted text or metadata")
    hits = [_Hit("This <video> has no captions or subtitles <track>.", v.open_start, v.close_end or v.open_end)
            for v in videos if not _CAPTION_TRACK.search(text[v.open_end:v.inner_end] if v.inner_end else "")]
    for item in meta.media:
        if item.kind == "video" and item.captions is False:
            hits.append(_Hit(f'Video "{item.ref}" has no captions (from metadata).'))
        if item.kind == "audio" and item.transcript is False:
            hits.append(_Hit(f'Audio "{item.ref}" has no transcript (from metadata).'))
    unknown = len(audio) + len(embeds) + sum(
        1 for i in meta.media if (i.kind == "video" and i.captions is None) or (i.kind == "audio" and i.transcript is None))
    inspected = len(videos) + len(meta.media) - sum(
        1 for i in meta.media if (i.kind == "video" and i.captions is None) or (i.kind == "audio" and i.transcript is None))
    if not hits and unknown and not inspected:
        raise _NotCheckable(f"{unknown} media item(s) whose captions or transcript cannot be inspected "
                            "(embedded players, <audio>, or metadata marked unknown)")
    return hits


def _rgb(value: str) -> tuple[float, float, float] | None:
    value = value.strip().lower().removesuffix("!important").strip()
    m = re.fullmatch(r"#([0-9a-f]{3}|[0-9a-f]{6})", value)
    if m:
        h = m.group(1)
        h = "".join(c * 2 for c in h) if len(h) == 3 else h
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]
    m = re.fullmatch(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", value)
    if m and all(int(g) <= 255 for g in m.groups()):
        return tuple(int(g) / 255 for g in m.groups())  # type: ignore[return-value]
    return None


def contrast_ratio(foreground: tuple[float, float, float], background: tuple[float, float, float]) -> float:
    """WCAG 2 contrast ratio between two sRGB colours (channels in 0..1)."""
    def luminance(rgb: tuple[float, float, float]) -> float:
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _contrast(text: str, meta: ContentMetadata, style: StyleRules) -> list[_Hit]:
    hits, inspected = [], 0
    for m in _ANY_TAG.finditer(text):
        attr = _STYLE_ATTR.search(m.group(0))
        if not attr:
            continue
        css = attr.group(2) if attr.group(2) is not None else attr.group(3)
        fg, bg = _CSS_COLOR.search(css), _CSS_BACKGROUND.search(css)
        if not fg or not bg:
            continue
        a, b = _rgb(fg.group(1)), _rgb(bg.group(1))
        if a is None or b is None:
            continue  # named colours, gradients, variables: not inspectable
        inspected += 1
        ratio = contrast_ratio(a, b)
        if ratio < style.min_contrast_ratio:
            hits.append(_Hit(f"Text colour against its background is {ratio:.2f}:1; at least {style.min_contrast_ratio:g}:1 is needed.",
                             m.start(), m.end()))
    for pair in meta.colors:
        a, b = _rgb(pair.foreground), _rgb(pair.background)
        if a is None or b is None:
            continue
        inspected += 1
        needed = style.min_contrast_ratio_large_text if pair.large_text else style.min_contrast_ratio
        ratio = contrast_ratio(a, b)
        if ratio < needed:
            hits.append(_Hit(f'"{pair.ref}": contrast {ratio:.2f}:1, at least {needed:g}:1 is needed (from metadata).'))
    if not inspected:
        raise _NotCheckable("no text/background colour pair with parseable colours in the submitted text or metadata")
    return hits
