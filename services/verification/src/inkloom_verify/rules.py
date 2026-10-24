"""Deterministic brand-rule checks, run before claim extraction (no model call).

The rules arrive with the request (``VerificationRequest.rules``, schema ``BrandRules`` in
schemas.py). Five rule types:

* ``required_term``: the content must contain the term (case-insensitive, whole words);
* ``prohibited_term``: every occurrence of the term is flagged;
* ``product_naming``: every case-insensitive occurrence of the approved name or a listed variant
  that is not written exactly as approved is flagged ("lumen pods", "LumenPods" for "Lumen Pods");
* ``required_disclaimer``: the disclaimer text must appear (whitespace and case ignored), always
  or only when a trigger term appears;
* ``numeric_limit``: a figure written with one of the rule's units, in a sentence that mentions
  the rule's subject, must lie within the rule's range.

Accessibility and tone (``BrandRules.style``, schema ``StyleRules``; not brand-specific):

* ``all_caps_run``: at least ``all_caps_min_words`` consecutive upper-case words of two or more
  letters ("BUY NOW TODAY"); words in ``allowed_caps`` (acronyms, model names) neither count nor
  break a run on their own;
* ``emoji_run``: more than ``emoji_max_run`` emoji in a row (spaces between them do not break the
  run; skin-tone modifiers, variation selectors and joiners are part of one emoji);
* ``vague_link_text``: Markdown or HTML link text that is one of ``vague_link_phrases`` ("click
  here", "read more"), plus the bare phrase "click here" anywhere in plain text (single words like
  "here" are only flagged as link text, since they are ordinary words elsewhere);
* ``missing_alt_text``: a Markdown image with empty alt text (``![](photo.png)``) or an HTML
  ``<img>`` without an ``alt`` attribute. ``alt=""`` is not flagged: WCAG uses it for decorative
  images, so a person decides.

Each violation becomes a ``RuleFinding`` in the shared finding contract's shape: check_type
``rule``, verification_status ``not_applicable``, requires_human_review always true. Evidence and
``source_ids`` come only from the rule's ``source`` (validated against the request's references);
a suggested correction exists only for a sourced rule that names the approved wording.

Known limits: matching is literal (no stemming or synonyms, so "guaranteed" does not match a
rule on "guarantee"), sentence splitting is punctuation-based, and a numeric rule reads only
figures written as digits next to one of its units. The style checks read Markdown and simple
HTML in the submitted text only; they do not render pages, check colour contrast or reading
level, and an emoji is recognised by its Unicode block, so a few symbols (e.g. ☺ written as text)
count as emoji.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator

from inkloom_verify.schemas import (
    MAX_RULE_FINDINGS,
    MAX_RULE_TEXT_CHARS,
    BrandRules,
    NumericLimitRule,
    ProductNamingRule,
    RuleEvidence,
    RuleFinding,
    RuleSeverity,
    RuleType,
    SourceSpan,
    StyleRules,
    _Rule,
)

logger = logging.getLogger(__name__)

_SENTENCE = re.compile(r"[^.!?\n]+[.!?]?")
_NUMBER = r"(\d+(?:[.,]\d+)*)"


def term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive, whitespace-tolerant; whole words where the term starts or ends with one."""
    body = r"\s+".join(re.escape(part) for part in term.split())
    start = r"(?<![\w])" if term[:1].isalnum() else ""
    end = r"(?![\w])" if term[-1:].isalnum() else ""
    return re.compile(start + body + end, re.IGNORECASE)


def _matches(term: str, text: str) -> Iterator[re.Match[str]]:
    return term_pattern(term).finditer(text)


def _normalised(text: str) -> str:
    return " ".join(text.split()).casefold()


def _clip(text: str) -> str:
    return text if len(text) <= MAX_RULE_TEXT_CHARS else text[: MAX_RULE_TEXT_CHARS - 1] + "…"


class _Builder:
    def __init__(self) -> None:
        self.findings: list[RuleFinding] = []
        self._counts: dict[str, int] = {}

    def add(self, rule: _Rule, rule_type: RuleType, explanation: str, match: re.Match[str] | None = None,
            correction: str | None = None) -> None:
        n = self._counts.get(rule.rule_id, 0) + 1
        self._counts[rule.rule_id] = n
        evidence = [RuleEvidence(source_id=rule.source.doc_id, quote=rule.source.quote)] if rule.source else []
        self.findings.append(RuleFinding(
            finding_id=f"rul_{rule.rule_id}_{n}",
            rule_id=rule.rule_id,
            rule_type=rule_type,
            severity=rule.severity,
            original_text=match.group(0) if match else "",
            span=SourceSpan(start=match.start(), end=match.end()) if match else None,
            explanation=_clip(explanation),
            source_ids=[e.source_id for e in evidence],
            evidence=evidence,
            # Only an approved, quoted rule may supply replacement wording.
            suggested_correction=correction if (correction and evidence and match) else None,
        ))


def check_rules(text: str, rules: BrandRules | None) -> list[RuleFinding]:
    """Every violation of ``rules`` in ``text``, in rule order, at most MAX_RULE_FINDINGS."""
    if rules is None:
        return []
    out = _Builder()
    for rule in rules.required_terms:
        if next(_matches(rule.term, text), None) is None:
            out.add(rule, RuleType.REQUIRED_TERM, f'The required term "{rule.term}" does not appear.')
    for rule in rules.prohibited_terms:
        for match in _matches(rule.term, text):
            out.add(rule, RuleType.PROHIBITED_TERM, f'"{match.group(0)}" is a prohibited term.',
                    match, rule.approved_alternative)
    for rule in rules.product_names:
        for match in _naming_violations(rule, text):
            out.add(rule, RuleType.PRODUCT_NAMING,
                    f'"{match.group(0)}" is not the approved product name "{rule.approved_name}".',
                    match, rule.approved_name)
    content = _normalised(text)
    for rule in rules.disclaimers:
        triggered = not rule.trigger_terms or any(next(_matches(t, text), None) for t in rule.trigger_terms)
        if triggered and _normalised(rule.disclaimer) not in content:
            out.add(rule, RuleType.REQUIRED_DISCLAIMER, f'The required disclaimer "{rule.disclaimer}" is missing.')
    for rule in rules.numeric_limits:
        for match, value in _figures(rule, text):
            low, high = rule.minimum, rule.maximum
            if (low is not None and value < low) or (high is not None and value > high):
                bound = " to ".join(f"{b:g}" for b in (low, high) if b is not None)
                limit = (f"between {low:g} and {high:g}" if low is not None and high is not None
                         else f"at most {high:g}" if high is not None else f"at least {low:g}")
                out.add(rule, RuleType.NUMERIC_LIMIT,
                        f'"{match.group(0)}" for {rule.subject} breaks the rule: it must be {limit} ({bound}).', match)
    if rules.style is not None:
        _check_style(rules.style, text, out)
    if len(out.findings) > MAX_RULE_FINDINGS:
        logger.info("rules: %d findings, only the first %d kept", len(out.findings), MAX_RULE_FINDINGS)
    return out.findings[:MAX_RULE_FINDINGS]


def _naming_violations(rule: ProductNamingRule, text: str) -> Iterator[re.Match[str]]:
    """Occurrences of the approved name or a variant not written exactly as approved; longest
    pattern first, never overlapping."""
    taken: list[tuple[int, int]] = []
    for name in sorted({rule.approved_name, *rule.variants}, key=len, reverse=True):
        for match in _matches(name, text):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            if match.group(0) != rule.approved_name:
                yield match


def _figures(rule: NumericLimitRule, text: str) -> Iterator[tuple[re.Match[str], float]]:
    """(match of "<number> <unit>", value) in sentences that mention the rule's subject."""
    units = "|".join(re.escape(u) for u in sorted(rule.units, key=len, reverse=True))
    figure = re.compile(_NUMBER + r"\s*(?:" + units + r")(?![\w])", re.IGNORECASE)
    subject = term_pattern(rule.subject)
    for sentence in _SENTENCE.finditer(text):
        if not subject.search(sentence.group(0)):
            continue
        for match in figure.finditer(text, sentence.start(), sentence.end()):
            number = match.group(1)
            # "1,200" is twelve hundred; "4,5" (one to two digits after the comma) is a decimal comma.
            value = float(number.replace(",", "") if re.search(r",\d{3}(?!\d)", number) else number.replace(",", "."))
            yield match, value


# --- Accessibility and tone -----------------------------------------------------------------------

STYLE_RULE_IDS = {
    RuleType.ALL_CAPS_RUN: "style.all_caps",
    RuleType.EMOJI_RUN: "style.emoji",
    RuleType.VAGUE_LINK_TEXT: "style.link_text",
    RuleType.MISSING_ALT_TEXT: "style.alt_text",
}
BARE_VAGUE_PHRASES = ("click here",)  # flagged in plain text too, not only as link text

_WORD = re.compile(r"[^\W\d_][\w'’-]*")
_EMOJI_BASE = (r"[\U0001F000-\U0001F02F\U0001F0A0-\U0001F0FF\U0001F100-\U0001F1FF\U0001F200-\U0001F2FF"
               r"\U0001F300-\U0001F5FF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F700-\U0001F77F"
               r"\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FAFF"
               r"\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF]")
_EMOJI_MODIFIER = r"[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF\u20E3]"
_ONE_EMOJI = _EMOJI_BASE + _EMOJI_MODIFIER + "*(?:\u200D" + _EMOJI_BASE + _EMOJI_MODIFIER + "*)*"
_EMOJI_RUN = re.compile("(?:" + _ONE_EMOJI + ")(?:[ \t]*(?:" + _ONE_EMOJI + "))*")
_ONE_EMOJI_RE = re.compile(_ONE_EMOJI)
_MD_LINK = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\s]*)[^)]*\)")
_HTML_LINK = re.compile(r"<a\b[^>]*>(.*?)</a\s*>", re.IGNORECASE | re.DOTALL)
_MD_IMAGE = re.compile(r"!\[([^\]\n]*)\]\(([^)]*)\)")
_HTML_IMG = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
_ALT_ATTR = re.compile(r"\balt\s*=", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")


def _style_rule(rules: StyleRules, rule_type: RuleType) -> _Rule:
    return _Rule(rule_id=STYLE_RULE_IDS[rule_type], severity=rules.severity)


class _Span:
    """A match-like (start, end, text) for spans that are not one regex match."""

    def __init__(self, text: str, start: int, end: int) -> None:
        self._text, self._start, self._end = text, start, end

    def group(self, _: int = 0) -> str:
        return self._text[self._start:self._end]

    def start(self) -> int:
        return self._start

    def end(self) -> int:
        return self._end


def _check_style(rules: StyleRules, text: str, out: _Builder) -> None:
    if rules.all_caps:
        rule = _style_rule(rules, RuleType.ALL_CAPS_RUN)
        for span, count in _caps_runs(text, rules.all_caps_min_words, {a.casefold() for a in rules.allowed_caps}):
            out.add(rule, RuleType.ALL_CAPS_RUN,
                    f"{count} words in a row are in capitals; screen readers may spell them out and readers "
                    "read it as shouting.", span)
    if rules.emoji:
        rule = _style_rule(rules, RuleType.EMOJI_RUN)
        for match in _EMOJI_RUN.finditer(text):
            count = len(_ONE_EMOJI_RE.findall(match.group(0)))
            if count > rules.emoji_max_run:
                out.add(rule, RuleType.EMOJI_RUN,
                        f"{count} emoji in a row (at most {rules.emoji_max_run}); screen readers read every one aloud.",
                        match)
    if rules.vague_link_text:
        rule = _style_rule(rules, RuleType.VAGUE_LINK_TEXT)
        vague = {" ".join(p.split()).casefold() for p in rules.vague_link_phrases}
        flagged: list[tuple[int, int]] = []
        for span in _link_texts(text):
            if " ".join(_TAG.sub(" ", span.group(0)).split()).casefold().strip(" .:!") in vague:
                flagged.append((span.start(), span.end()))
                out.add(rule, RuleType.VAGUE_LINK_TEXT,
                        f'Link text "{span.group(0).strip()}" does not say where the link goes.', span)
        for phrase in BARE_VAGUE_PHRASES:
            for match in _matches(phrase, text):
                if not any(match.start() < end and start < match.end() for start, end in flagged):
                    out.add(rule, RuleType.VAGUE_LINK_TEXT,
                            f'"{match.group(0)}" does not say what happens; name the destination or action.', match)
    if rules.alt_text:
        rule = _style_rule(rules, RuleType.MISSING_ALT_TEXT)
        for match in _MD_IMAGE.finditer(text):
            if not match.group(1).strip():
                out.add(rule, RuleType.MISSING_ALT_TEXT,
                        "This image has no alt text, so screen-reader users get nothing from it.", match)
        for match in _HTML_IMG.finditer(text):
            if not _ALT_ATTR.search(match.group(0)):
                out.add(rule, RuleType.MISSING_ALT_TEXT,
                        'This <img> has no alt attribute. Describe the image, or use alt="" if it is decorative.',
                        match)


def _caps_runs(text: str, min_words: int, allowed: set[str]) -> Iterator[tuple[_Span, int]]:
    """Runs of upper-case words (2+ letters) on one line; allowed words are skipped."""
    run: list[re.Match[str]] = []

    def flush() -> Iterator[tuple[_Span, int]]:
        if len(run) >= min_words:
            yield _Span(text, run[0].start(), run[-1].end()), len(run)

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


def _link_texts(text: str) -> Iterator[_Span]:
    for match in _MD_LINK.finditer(text):
        yield _Span(text, match.start(1), match.end(1))
    for match in _HTML_LINK.finditer(text):
        inner = match.group(1)
        if inner.strip():
            yield _Span(text, match.start(1), match.end(1))
