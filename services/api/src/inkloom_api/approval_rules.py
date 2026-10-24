"""Review decision state machine.

A review may be decided (approved / rejected / changes_requested) only from `completed` or
`needs_human_review`. Every other state is either not finished yet (draft/queued/analysing),
already decided (approved/rejected/changes_requested), or has nothing to decide on
(failed/source_changed) - in all of those cases a decision attempt is an invalid transition, not
a permission problem, so routers report it as 409, never 403 (phase6 "Tests (write now)":
"Non-approver gets a safe 403 or 409" - 403 is the separate permission check, this module is the
409 half).

Pure logic, no DB, no FastAPI - every function here is a plain predicate or a plain exception, so
the state machine itself is testable without a database.

Individual-user mode (2026-10-24): the Phase 9 risk-based routing guard (`RoutingMismatchError` /
`ensure_role_matches_routing`, "only a legal_reviewer may approve a high-risk review") was removed
here - every account has exactly one person, who approves their own content. The guards that
still make sense in a one-person account all remain: the review must be finished, the version
must be current, and a cited source must not have been replaced since the review ran.
"""

from __future__ import annotations

from .statuses import ReviewState

DECIDABLE_STATES = frozenset({ReviewState.COMPLETED.value, ReviewState.NEEDS_HUMAN_REVIEW.value})


class InvalidReviewTransitionError(Exception):
    """A decision was attempted on a review that isn't in a decidable state."""

    def __init__(self, review_status: str) -> None:
        self.review_status = review_status
        super().__init__(f"cannot decide a review in status '{review_status}'")


class StaleApprovalError(Exception):
    """The content has moved on to a newer version since this review ran
    (governance invariant, docs/backend.md: `current_version_id != reviewed_version_id`)."""


class SupersededSourceError(Exception):
    """A source this review cited is no longer the approved version of that brand source."""

    def __init__(self, brand_source_id: str) -> None:
        self.brand_source_id = brand_source_id
        super().__init__(f"cited source {brand_source_id} was superseded after this review ran")


def ensure_decidable(review_status: str) -> None:
    if review_status not in DECIDABLE_STATES:
        raise InvalidReviewTransitionError(review_status)


def ensure_not_stale(
    reviewed_content_version_id: object, current_content_version_id: object
) -> None:
    if reviewed_content_version_id != current_content_version_id:
        raise StaleApprovalError()
