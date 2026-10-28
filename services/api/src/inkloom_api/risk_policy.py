"""Risk-based routing: the one place that turns a review's findings into a risk level and a
routing decision (Round 3 Phase 4; contracts.md section 19; docs/governance.md section 7).

Pure logic over plain values - no DB, no FastAPI - so it is testable without a database and
changing the mapping is an edit to this file only.

Section 19, per finding (first match wins):

| signal                                                      | risk   | code                |
|-------------------------------------------------------------|--------|---------------------|
| verification_status `contradicted`                          | high   | contradicted_claim  |
| `conflicting_sources`                                       | medium | conflicting_sources |
| category `engine_error` (the claim could not be checked)    | medium | engine_error        |
| category `stub` (no AI provider: nothing was checked)       | medium | not_checked         |
| `unverified` (no evidence either way)                       | medium | unverified_claim    |
| any status or review reason this module doesn't know        | medium | unknown_signal      |
| anything else with requires_human_review (flagged)          | low    | flagged_for_review  |
| otherwise                                                   | clean  | clean               |

Unknown values are never rejected: they are passed through as-is in the triggers and routed
conservatively (Krish: new reason codes such as property_mismatch or unsupported_clause, or a new
status, must not break anything). A review whose brand rules did not all run is at least medium.
The draft's level is its highest finding. Clean goes to an approver only; everything else needs a
reviewer first.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .statuses import ReviewState, RiskLevel, RulesStatus

KNOWN_VERIFICATION_STATUSES = frozenset(
    {"supported", "contradicted", "unverified", "conflicting_sources", "not_applicable"}
)
# inkloom_verify.schemas.ClaimReviewReason today.
KNOWN_REVIEW_REASONS = frozenset(
    {
        "contradicted",
        "not_enough_evidence",
        "error",
        "weak_evidence",
        "below_policy_strength",
        "compound_under_cited",
    }
)
# Rule findings counted as "tone" in summary counts: the engine's style checks
# (inkloom_verify/rules.py, "Accessibility and tone"). Narrow on purpose - there is no tone
# checker yet (DECISIONS_PENDING.md).
TONE_RULE_TYPES = frozenset({"all_caps_run", "emoji_run"})

_ORDER = {RiskLevel.CLEAN: 0, RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}

REVIEWER = "reviewer"
APPROVER = "approver"


def risk_rank(level: str | None) -> int:
    """Comparable rank for a stored level; unknown or missing ranks as medium (conservative)."""
    try:
        return _ORDER[RiskLevel(level)]
    except ValueError:
        return _ORDER[RiskLevel.MEDIUM]


@dataclass(frozen=True)
class Trigger:
    finding_id: str
    verification_status: str
    review_reasons: list[str]
    risk_level: str
    code: str

    def as_dict(self) -> dict:
        return {
            "finding_id": self.finding_id,
            "verification_status": self.verification_status,
            "review_reasons": self.review_reasons,
            "risk_level": self.risk_level,
            "code": self.code,
        }


@dataclass(frozen=True)
class RiskAssessment:
    """`blocked` is set when there is nothing to judge: the AI check failed or a cited source
    changed. Then `level` is None and the draft can't move on until it is re-checked."""

    level: str | None
    required_reviewer_role: str | None
    reason_code: str
    reason_text: str
    triggers: list[Trigger] = field(default_factory=list)
    blocked: bool = False

    @property
    def needs_reviewer(self) -> bool:
        return self.required_reviewer_role == REVIEWER

    def routing_reason(self) -> dict:
        return {
            "code": self.reason_code,
            "text": self.reason_text,
            "triggered_by": [
                {k: v for k, v in t.as_dict().items() if k != "code"} for t in self.triggers
            ],
        }


def finding_risk(finding) -> tuple[RiskLevel, str]:
    status = finding.verification_status
    reasons = list(finding.review_reasons or [])
    if status == "contradicted":
        return RiskLevel.HIGH, "contradicted_claim"
    if status == "conflicting_sources":
        return RiskLevel.MEDIUM, "conflicting_sources"
    if finding.category == "engine_error":
        return RiskLevel.MEDIUM, "engine_error"
    if finding.category == "stub":
        return RiskLevel.MEDIUM, "not_checked"
    if status == "unverified":
        return RiskLevel.MEDIUM, "unverified_claim"
    if status not in KNOWN_VERIFICATION_STATUSES or any(
        reason not in KNOWN_REVIEW_REASONS for reason in reasons
    ):
        return RiskLevel.MEDIUM, "unknown_signal"
    if finding.requires_human_review:
        return RiskLevel.LOW, "flagged_for_review"
    return RiskLevel.CLEAN, "clean"


_TEXT = {
    "contradicted_claim": "{n} claim{s} {are} contradicted by an approved source",
    "conflicting_sources": "{n} claim{s} {are} covered by approved sources that disagree",
    "engine_error": "{n} claim{s} could not be checked",
    "not_checked": "no AI provider is configured, so nothing was checked",
    "unverified_claim": "{n} claim{s} {have} no evidence either way",
    "unknown_signal": "{n} finding{s} carr{ies} a verification result this version doesn't know",
    "flagged_for_review": "{n} finding{s} {are} flagged for a person to look at",
    "rules_incomplete": "not every brand rule could be checked",
}


def _sentence(code: str, n: int) -> str:
    one = n == 1
    return _TEXT[code].format(
        n=n,
        s="" if one else "s",
        are="is" if one else "are",
        have="has" if one else "have",
        ies="ies" if one else "y",
    )


def assess(review, findings) -> RiskAssessment | None:
    """The routing decision for one finished review; None while it is still running."""
    if review.status == ReviewState.FAILED.value:
        return RiskAssessment(
            None, None, "ai_check_failed", "The AI check failed. Re-check the draft.", blocked=True
        )
    if review.status == ReviewState.SOURCE_CHANGED.value:
        return RiskAssessment(
            None,
            None,
            "source_changed",
            "A source this check cited has changed since. Re-check the draft.",
            blocked=True,
        )
    if review.status in (
        ReviewState.DRAFT.value,
        ReviewState.QUEUED.value,
        ReviewState.ANALYSING.value,
    ):
        return None

    scored = [(finding, *finding_risk(finding)) for finding in findings]
    triggers = sorted(
        (
            Trigger(
                str(f.finding_id),
                f.verification_status,
                list(f.review_reasons or []),
                level.value,
                code,
            )
            for f, level, code in scored
            if level is not RiskLevel.CLEAN
        ),
        key=lambda t: -_ORDER[RiskLevel(t.risk_level)],
    )
    level = max((lvl for _, lvl, _ in scored), key=_ORDER.get, default=RiskLevel.CLEAN)
    codes = [t.code for t in triggers]
    if review.rules_status in (RulesStatus.INCOMPLETE.value, RulesStatus.NOT_APPLIED.value):
        if _ORDER[level] < _ORDER[RiskLevel.MEDIUM]:
            level = RiskLevel.MEDIUM
        codes.append("rules_incomplete")

    if level is RiskLevel.CLEAN:
        return RiskAssessment(
            RiskLevel.CLEAN.value,
            APPROVER,
            "clean",
            "Every claim is supported by an approved source and nothing was flagged, so no "
            "reviewer step is needed.",
        )
    # The headline reason is the most serious code; the text names every kind found.
    top = next(t.code for t in triggers if t.risk_level == level.value) if triggers else codes[0]
    parts = [_sentence(code, codes.count(code)) for code in dict.fromkeys([top, *codes])]
    text = "; ".join(parts)
    text = f"{text[0].upper()}{text[1:]}, so a reviewer must check this draft before it can be approved."
    return RiskAssessment(level.value, REVIEWER, top, text, triggers[:50])


def summary_counts(findings) -> dict[str, int]:
    """Server-side counts for one review (docs/governance.md 9.4). Dismissed findings still
    count; an unknown verification status counts as unverified."""
    counts = {
        "supported": 0,
        "contradicted": 0,
        "unverified": 0,
        "conflicting": 0,
        "tone": 0,
        "needs_human_review": 0,
    }
    for f in findings:
        status = f.verification_status
        if status == "supported":
            counts["supported"] += 1
        elif status == "contradicted":
            counts["contradicted"] += 1
        elif status == "conflicting_sources":
            counts["conflicting"] += 1
        elif status == "unverified" or status not in KNOWN_VERIFICATION_STATUSES:
            counts["unverified"] += 1
        if f.check_type == "rule" and f.rule_type in TONE_RULE_TYPES:
            counts["tone"] += 1
        if f.requires_human_review:
            counts["needs_human_review"] += 1
    return counts
