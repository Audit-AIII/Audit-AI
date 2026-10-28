"""Brand rules on a review: Member 2's deterministic rules module, wired into the pipeline.

The checks themselves (terminology, brand compliance, accessibility) are entirely the engine's
(`inkloom_verify.rules.evaluate_rules`, contract in services/verification/RULES_HANDOFF.md); this
module only runs them on the content version and stores what they return:

* each rule finding as a `Finding` (check_type "rule", verification_status "not_applicable",
  always requires_human_review), via the engine's own `rule_finding_fields` mapping;
* one check record per rule on the review (`rule_checks`), so "not checkable" is never shown as
  "passed", plus `rules_status`: complete / incomplete (a check ended in error) / not_applied
  (the stored rules are invalid, or the rules module failed - nothing ran, no finding is made up).

The backend never trusts the engine: a rule finding's evidence is kept only if its document is
one of this brand's current approved sources and the quote is really in that document's text.
A suggestion whose stated basis is that document is dropped with it.

No model call, no network: it runs on every review path (cache hit, no provider, no sources),
and its results are never cached - rules can change without the content changing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from inkloom_verify.integration import proposed_rule_finding_fields, rule_finding_fields
from inkloom_verify.rules import RuleEvaluationError, evaluate_rules
from inkloom_verify.schemas import RuleEvidence, RuleFinding, SourceSpan
from sqlalchemy.orm import Session

from ..intent_lock_guard import breaks_locks
from ..models import ContentVersion, EvidenceLink, Finding, Review
from ..section_diff import section_hash_for_span
from ..statuses import CheckType, EvidenceRelation, RulesStatus, VerificationStatus
from .corpus import CorpusEntry

logger = logging.getLogger(__name__)

NOT_APPLIED = "Brand rules could not be applied"


@dataclass(frozen=True)
class RulesOutcome:
    needs_human_review: bool
    note: str | None  # joined into the review's error_summary; field names and rule ids only


def apply_brand_rules(
    db: Session,
    review: Review,
    content_version: ContentVersion,
    brand_rules: dict | None,
    corpus: list[CorpusEntry],
    locks: list[str] = (),
) -> RulesOutcome:
    try:
        evaluation = evaluate_rules(content_version.text, brand_rules)
    except RuleEvaluationError as error:
        # Rules are validated when saved, so this means they no longer validate (e.g. an engine
        # upgrade tightened a rule). `problems` names fields and rule ids, never configured values.
        review.rules_status = RulesStatus.NOT_APPLIED.value
        detail = "; ".join(error.problems) or str(error)
        return RulesOutcome(True, f"{NOT_APPLIED}: {detail}"[:500])
    except Exception as error:  # noqa: BLE001 - one failed check must not fail the review
        logger.error("review=%s rules failed unexpectedly: %s", review.id, type(error).__name__)
        review.rules_status = RulesStatus.NOT_APPLIED.value
        return RulesOutcome(
            True, f"{NOT_APPLIED}: the rules check failed unexpectedly ({type(error).__name__})."
        )

    documents = {entry.document.doc_id: entry for entry in corpus}
    for finding in evaluation.findings:
        _write_rule_finding(db, review, finding, documents, content_version.text, locks)
    review.rule_checks = [check.model_dump(mode="json") for check in evaluation.checks]
    review.rules_status = (
        RulesStatus.COMPLETE if evaluation.complete else RulesStatus.INCOMPLETE
    ).value

    notes = []
    if not evaluation.complete:
        notes.append(
            "Some brand rule checks could not run, so this draft is not shown as rule-clean."
        )
    if evaluation.truncated:
        notes.append(
            f"Only the first {len(evaluation.findings)} rule findings are listed; "
            "rule_checks has the full counts."
        )
    return RulesOutcome(
        bool(evaluation.findings) or not evaluation.complete, " ".join(notes) or None
    )


def _resolve(
    evidence: RuleEvidence, documents: dict[str, CorpusEntry]
) -> tuple[CorpusEntry, SourceSpan] | None:
    entry = documents.get(evidence.source_id)
    start = entry.document.text.find(evidence.quote) if entry is not None else -1
    if start < 0:
        return None
    return entry, SourceSpan(start=start, end=start + len(evidence.quote))


def _write_rule_finding(
    db: Session,
    review: Review,
    finding: RuleFinding,
    documents: dict[str, CorpusEntry],
    text: str,
    locks: list[str],
) -> None:
    fields = rule_finding_fields(finding)
    extra = proposed_rule_finding_fields(finding)
    resolved = [(e, r) for e in finding.evidence if (r := _resolve(e, documents)) is not None]
    suggestion, basis = fields["suggested_correction"], extra["suggestion_basis"]
    if len(resolved) < len(finding.evidence):
        logger.warning(
            "review=%s rule=%s: %d rule evidence item(s) not in an approved source, dropped",
            review.id,
            finding.rule_id,
            len(finding.evidence) - len(resolved),
        )
        if basis == "approved_document":
            suggestion = basis = None  # its stated basis is gone
    if breaks_locks(text, finding.span.start, finding.span.end, suggestion, locks):
        suggestion = basis = None  # Intent-lock: would remove a must-keep phrase

    row = Finding(
        review_id=review.id,
        category=fields["category"],
        severity=fields["severity"],
        original_text=fields["original_text"],
        span_start=fields["span"]["start"],
        span_end=fields["span"]["end"],
        check_type=CheckType.RULE.value,
        explanation=fields["explanation"],
        verification_status=VerificationStatus.NOT_APPLICABLE.value,
        suggested_correction=suggestion,
        requires_human_review=True,
        rule_id=extra["rule_id"],
        rule_type=extra["rule_type"],
        scope=extra["scope"],
        suggestion_basis=basis,
    )
    db.add(row)
    db.flush()  # assigns finding_id for the evidence rows
    for evidence, (entry, span) in resolved:
        db.add(
            EvidenceLink(
                finding_id=row.finding_id,
                source_id=entry.brand_source_id,
                source_version_id=entry.source_version_id,
                quote=evidence.quote,
                relation=EvidenceRelation.CONTRADICTS.value,  # the content breaks the quoted rule
                cited_section_hash=section_hash_for_span(entry.document, span),
            )
        )
