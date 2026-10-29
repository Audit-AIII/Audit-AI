"""The decision policy: which verified claims a person must review (EVAL.md Phase 5).

**No calibrated confidence exists, so none is used.** The model is never asked for a confidence
(its output schema has no such field, and a reply carrying one is refused), and the engine's
``EvidenceStrength`` is an ordinal label from fixed rules, not a probability. The policy therefore
decides from evidence the code has checked (the verdict, the accepted citations, and their
rank), never from a score that would only look statistical.

**Two layers:**

1. The fixed floor (``schemas.floor_review_reasons``): not configurable, enforced by the
   ``ClaimResult`` contract. CONTRADICTED, NOT_ENOUGH_EVIDENCE and ERROR always go to a person,
   and so does SUPPORTED on weak evidence (no accepted citation from the top-ranked passage). A
   missing source or a conflict between references is NOT_ENOUGH_EVIDENCE (the citation guard's
   ``conflicting_evidence``), so both always go to a person and never count as support.
2. This policy (configurable, ``DecisionPolicy``): it can only route **more** SUPPORTED claims to
   a person, never fewer. Its two thresholds are bounded so that no setting is looser than the
   floor:

   * ``auto_clear_min_strength``: the weakest evidence on which a SUPPORTED claim may skip review:
     ``strong`` (default), ``moderate``, or ``never`` (every claim goes to a person). ``weak`` and
     ``none`` cannot be configured.
   * ``compound_min_citations``: a SUPPORTED claim that looks compound (``looks_compound``: joined
     by "and", "but", "while", "as well as", "plus" or a semicolon) skips review only with at least
     this many accepted citations (1 to 3; default 2). One quote rarely settles two facts, and a
     figure-free part cannot be checked by the support checks, so a compound claim on one quote
     goes to a person.

**Priority: missed contradictions before review volume.** Wrongly clearing a claim that is not
true costs more than one extra review. The defaults were chosen by that rule, not tuned: no
model-backed outcomes on the development split exist yet. ``evaluation/calibrate.py`` selects
thresholds on the development split only, and requires that no non-SUPPORTED record is
auto-cleared before it minimises review volume.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from inkloom_verify.schemas import (
    ClaimResult,
    ClaimReviewReason,
    EvidenceStrength,
    Verdict,
    floor_review_reasons,
)

POLICY_VERSION = "decision-policy-v1"
_STRENGTH_ORDER = {
    EvidenceStrength.NONE: 0,
    EvidenceStrength.WEAK: 1,
    EvidenceStrength.MODERATE: 2,
    EvidenceStrength.STRONG: 3,
}
_COMPOUND = re.compile(r"\b(?:and|but|while|whereas|plus|as well as)\b|;", re.IGNORECASE)


class DecisionPolicy(BaseModel):
    """Configurable review thresholds. Unknown fields are refused, so the floor cannot be switched off."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal["decision-policy-v1"] = POLICY_VERSION
    auto_clear_min_strength: Literal["moderate", "strong", "never"] = "strong"
    compound_min_citations: Annotated[int, Field(strict=True, ge=1, le=3)] = 2


FIXED_RULES = [
    "CONTRADICTED, NOT_ENOUGH_EVIDENCE and ERROR always require human review",
    "SUPPORTED on weak evidence (no accepted citation from the top-ranked passage) requires human review",
    "a missing source or conflicting references give NOT_ENOUGH_EVIDENCE, never SUPPORTED",
    "a policy can add review reasons to SUPPORTED claims, never remove one (ClaimResult contract)",
    "no model confidence is used: none is requested, and a reply carrying one is refused",
]


def looks_compound(statement: str) -> bool:
    """Whether a claim joins several facts. Deliberately broad: a false match only adds a review."""
    return _COMPOUND.search(statement) is not None


def review_reasons(
    verdict: Verdict,
    strength: EvidenceStrength,
    statement: str,
    accepted_citations: int,
    policy: DecisionPolicy,
) -> list[ClaimReviewReason]:
    """Every reason one claim must go to a person: the fixed floor, then the policy's additions."""
    reasons = floor_review_reasons(verdict, strength)
    if verdict is not Verdict.SUPPORTED:
        return reasons
    minimum = policy.auto_clear_min_strength
    if strength is not EvidenceStrength.WEAK and (
        minimum == "never" or _STRENGTH_ORDER[strength] < _STRENGTH_ORDER[EvidenceStrength(minimum)]
    ):
        reasons.append(ClaimReviewReason.BELOW_POLICY_STRENGTH)
    if looks_compound(statement) and accepted_citations < policy.compound_min_citations:
        reasons.append(ClaimReviewReason.COMPOUND_UNDER_CITED)
    return reasons


def apply_policy(result: ClaimResult, policy: DecisionPolicy) -> ClaimResult:
    """``result`` with the policy's review reasons; the floor reasons are always kept."""
    reasons = review_reasons(
        result.verdict,
        result.evidence_strength,
        result.claim.statement,
        len(result.citations),
        policy,
    )
    if reasons == list(result.review_reasons):
        return result
    data = result.model_dump()
    data.update(review_reasons=reasons, requires_human_review=bool(reasons))
    return ClaimResult.model_validate(data)


def describe(policy: DecisionPolicy) -> dict[str, object]:
    """The policy as recorded in evaluation reports."""
    return {
        "version": policy.version,
        "thresholds": policy.model_dump(mode="json", exclude={"version"}),
        "fixed_rules": FIXED_RULES,
        "uses_model_confidence": False,
    }
