"""Review decision state machine (phase6_versioning_approval_audit.md task 3).

A review may be decided (approved / rejected / changes_requested) only from `completed` or
`needs_human_review`. Every other state is either not finished yet (draft/queued/analysing),
already decided (approved/rejected/changes_requested), or has nothing to decide on
(failed/source_changed) - in all of those cases a decision attempt is an invalid transition, not
a permission problem, so routers report it as 409, never 403 (phase6 "Tests (write now)":
"Non-approver gets a safe 403 or 409" - 403 is the separate permission check, this module is the
409 half).

Pure logic, no DB, no FastAPI - every function here is a plain predicate or a plain exception, so
the state machine itself is testable without a database.
"""

from __future__ import annotations

from .statuses import MembershipRole, ReviewState

DECIDABLE_STATES = frozenset({ReviewState.COMPLETED.value, ReviewState.NEEDS_HUMAN_REVIEW.value})


class InvalidReviewTransitionError(Exception):
    """A decision was attempted on a review that isn't in a decidable state."""

    def __init__(self, review_status: str) -> None:
        self.review_status = review_status
        super().__init__(f"cannot decide a review in status '{review_status}'")


class StaleApprovalError(Exception):
    """The content has moved on to a newer version since this review ran
    (00_CONTEXT.md governance invariant: `current_version_id != reviewed_version_id`)."""


class SupersededSourceError(Exception):
    """A source this review cited is no longer the approved version of that brand source."""

    def __init__(self, brand_source_id: str) -> None:
        self.brand_source_id = brand_source_id
        super().__init__(f"cited source {brand_source_id} was superseded after this review ran")


class RoutingMismatchError(Exception):
    """Phase 9 stretch item 1: risk-based approval routing. A deterministic rule (see
    `engine/pipeline.py`'s `_compute_required_reviewer_role`) assigns every decidable review a
    `required_reviewer_role` — `legal_reviewer` for any high/critical finding, `brand_manager`
    otherwise. Only that role, or `admin` (the one role that bypasses every guard in this
    module, same as everywhere else), may *approve* it. This is deliberately narrower than
    `ensure_decidable`/`ensure_not_stale`/`SupersededSourceError`: it applies to approval only,
    never to request-changes/reject — rejecting stays safe for any reviewer regardless of risk
    tier, same reasoning as those guards not applying to request-changes either."""

    def __init__(self, required_reviewer_role: str, actor_role: str) -> None:
        self.required_reviewer_role = required_reviewer_role
        self.actor_role = actor_role
        super().__init__(f"this review requires role '{required_reviewer_role}' to approve, not '{actor_role}'")


def ensure_decidable(review_status: str) -> None:
    if review_status not in DECIDABLE_STATES:
        raise InvalidReviewTransitionError(review_status)


def ensure_not_stale(reviewed_content_version_id: object, current_content_version_id: object) -> None:
    if reviewed_content_version_id != current_content_version_id:
        raise StaleApprovalError()


def ensure_role_matches_routing(required_reviewer_role: str | None, actor_role: str) -> None:
    """No routing assigned yet (e.g. a cached/legacy review predating this feature) -> anyone
    with the APPROVE permission may still decide it, same as before this feature existed."""
    if required_reviewer_role is None or actor_role == MembershipRole.ADMIN.value:
        return
    if actor_role != required_reviewer_role:
        raise RoutingMismatchError(required_reviewer_role, actor_role)
