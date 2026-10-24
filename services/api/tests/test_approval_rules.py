"""Phase 6 task 3: the review decision state machine. No DB needed - pure predicates."""

from __future__ import annotations

import uuid

import pytest

from inkloom_api.approval_rules import (
    InvalidReviewTransitionError,
    StaleApprovalError,
    ensure_decidable,
    ensure_not_stale,
)


@pytest.mark.parametrize("status", ["completed", "needs_human_review"])
def test_decidable_states_do_not_raise(status: str) -> None:
    ensure_decidable(status)  # must not raise


@pytest.mark.parametrize(
    "status",
    [
        "draft",
        "queued",
        "analysing",
        "failed",
        "approved",
        "rejected",
        "changes_requested",
        "source_changed",
    ],
)
def test_non_decidable_states_raise(status: str) -> None:
    with pytest.raises(InvalidReviewTransitionError) as exc_info:
        ensure_decidable(status)
    assert exc_info.value.review_status == status


def test_matching_version_is_not_stale() -> None:
    version_id = uuid.uuid4()
    ensure_not_stale(version_id, version_id)  # must not raise


def test_mismatched_version_is_stale() -> None:
    with pytest.raises(StaleApprovalError):
        ensure_not_stale(uuid.uuid4(), uuid.uuid4())
