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

Each violation becomes a ``RuleFinding`` in the shared finding contract's shape: check_type
``rule``, verification_status ``not_applicable``, requires_human_review always true. Evidence and
``source_ids`` come only from the rule's ``source`` (validated against the request's references);
a suggested correction exists only for a sourced rule that names the approved wording.

Known limits: matching is literal (no stemming or synonyms, so "guaranteed" does not match a
rule on "guarantee"), sentence splitting is punctuation-based, and a numeric rule reads only
figures written as digits next to one of its units.
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
    RuleType,
    SourceSpan,
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
