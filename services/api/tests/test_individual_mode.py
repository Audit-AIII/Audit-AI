"""Individual-user mode (product decision 2026-10-24). Replaces test_risk_based_routing.py.

InkLoom is now a one-person-per-account app: one email = one private account (organisation), the
user owns all of it, and roles no longer gate anything. What used to be tested here (Phase 9
risk-based routing: high-severity reviews routed to `legal_reviewer`, everything else to
`brand_manager`, enforced at approval) is deliberately switched off. These tests pin the new
behaviour instead:

1. every new review has required_reviewer_role = null - including a real high-severity
   (CONTRADICTED) outcome through the real engine code, not just the stub;
   -> test_new_reviews_are_never_routed_stub_mode
   -> test_high_severity_review_is_not_routed
2. registration still makes the user "admin" (= account owner), and they approve their own
   content and request changes on it;
   -> test_registered_owner_approves_own_content
   -> test_owner_can_request_changes_on_own_content
3. an older review that still carries a routed role no longer restricts approval;
   -> test_legacy_routed_review_is_approvable_by_owner
4. a member with any legacy role name is treated as the account owner;
   -> test_legacy_role_names_act_as_account_owner
5. the guards that still make sense remain: unfinished/failed review, stale version (both also
   covered in test_content_versioning.py) and a replaced cited source.
   -> test_failed_review_still_cannot_be_approved
   -> test_replaced_cited_source_still_blocks_approval
6. DECISIONS.md: every decision is in the audit log - who decided, when, which version - and an
   approval never carries over to a newer version of the same draft.
   -> test_every_decision_is_audited_and_an_approval_never_carries_over
"""

from __future__ import annotations

import io
import uuid

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import AuditEvent, Membership, Review

CONTRADICTION_RULES = [
    ScriptedRule(
        "24 hours of playback per charge",
        "CONTRADICTED",
        "up to 12 hours of playback per charge",
        "The fact sheet gives 12 hours.",
    ),
]


def _approve(client, account, content_version_id: str):
    return client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=account.headers
    )


@requires_db
def test_new_reviews_are_never_routed_stub_mode(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    assert review["status"] == "needs_human_review"
    assert review["required_reviewer_role"] is None


@requires_db
def test_high_severity_review_is_not_routed(client, monkeypatch, account_factory) -> None:
    """A real CONTRADICTED verdict (severity high) - under Phase 9 this went to legal_reviewer."""
    use_scripted_provider(monkeypatch, CONTRADICTION_RULES)
    owner = account_factory("owner")
    review = owner.submit("Lumen Pods offer up to 24 hours of playback per charge.")
    [finding] = review["findings"]
    assert finding["verification_status"] == "contradicted"
    assert finding["severity"] == "high"
    assert review["required_reviewer_role"] is None
    assert (
        client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()[
            "required_reviewer_role"
        ]
        is None
    )


@requires_db
def test_registered_owner_approves_own_content(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, CONTRADICTION_RULES)
    owner = account_factory("owner")
    assert owner.role == "admin"  # "admin" now simply means "account owner"
    review = owner.submit("Lumen Pods offer up to 24 hours of playback per charge.")

    approved = _approve(client, owner, review["content_version_id"])
    assert approved.status_code == 201, approved.text
    assert approved.json()["action"] == "approved"
    assert approved.json()["actor_user_id"] == owner.user_id
    assert (
        client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()["status"]
        == "approved"
    )


@requires_db
def test_owner_can_request_changes_on_own_content(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    response = client.post(
        f"/api/content-versions/{review['content_version_id']}/request-changes",
        json={"decision": "changes_requested", "note": "soften the claim"},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["action"] == "changes_requested"


@requires_db
def test_legacy_routed_review_is_approvable_by_owner(
    client, force_stub_mode, db_session, account_factory
) -> None:
    """A review written before routing was turned off may still say "legal_reviewer"; that value
    is kept for history and no longer restricts who may approve."""
    owner = account_factory("owner")
    review = owner.submit()
    row = db_session.get(Review, uuid.UUID(review["id"]))
    row.required_reviewer_role = "legal_reviewer"
    db_session.commit()

    approved = _approve(client, owner, review["content_version_id"])
    assert approved.status_code == 201, approved.text


@requires_db
def test_legacy_role_names_act_as_account_owner(
    client, force_stub_mode, db_session, account_factory
) -> None:
    """Old rows may hold submitter/reviewer/... - each now holds every permission (no 403s)."""
    owner = account_factory("owner")
    for legacy_role in (
        "submitter",
        "reviewer",
        "source_manager",
        "approver",
        "brand_manager",
        "legal_reviewer",
    ):
        membership = db_session.query(Membership).filter_by(user_id=uuid.UUID(owner.user_id)).one()
        membership.role = legacy_role
        db_session.commit()

        review = owner.submit(
            f"Lumen Pods offer up to 12 hours of playback per charge ({legacy_role})."
        )
        assert _approve(client, owner, review["content_version_id"]).status_code == 201, legacy_role
        upload = client.post(
            f"/api/brands/{owner.brand_id}/sources",
            data={"title": f"Doc {legacy_role}", "approve": "true"},
            files={"file": ("d.txt", io.BytesIO(b"Warranty: 2 years."), "text/plain")},
            headers=owner.headers,
        )
        assert upload.status_code == 201, (legacy_role, upload.text)


@requires_db
def test_failed_review_still_cannot_be_approved(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner", with_source=False)  # no approved source -> review fails
    review = owner.submit()
    assert review["status"] == "failed"
    denied = _approve(client, owner, review["content_version_id"])
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "CONFLICT"


@requires_db
def test_replaced_cited_source_still_blocks_approval(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, CONTRADICTION_RULES)
    owner = account_factory("owner")
    review = owner.submit("Lumen Pods offer up to 24 hours of playback per charge.")
    withdrawn = client.post(
        f"/api/brands/{owner.brand_id}/sources/{owner.source_id}/withdraw",
        json={"status": "archived", "reason": "replaced by a newer fact sheet"},
        headers=owner.headers,
    )
    assert withdrawn.status_code == 200, withdrawn.text

    denied = _approve(client, owner, review["content_version_id"])
    assert denied.status_code == 409
    assert "rerun" in denied.json()["error"]["message"]


@requires_db
def test_every_decision_is_audited_and_an_approval_never_carries_over(
    client, force_stub_mode, db_session, account_factory
) -> None:
    owner = account_factory("owner")
    v1 = owner.submit()
    assert _approve(client, owner, v1["content_version_id"]).status_code == 201

    edited = client.post(
        f"/api/content/{v1['content_item_id']}/versions",
        json={"text": "Lumen Pods offer up to 12 hours of playback."},
        headers=owner.headers,
    )
    assert edited.status_code == 201, edited.text
    v2 = edited.json()
    assert v2["review"]["status"] != "approved"  # v1's approval does not carry over
    rejected = client.post(
        f"/api/content-versions/{v2['content_version_id']}/request-changes",
        json={"decision": "rejected", "note": "not ready"},
        headers=owner.headers,
    )
    assert rejected.status_code == 201, rejected.text

    db_session.expire_all()
    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.organisation_id == uuid.UUID(owner.organisation_id),
            AuditEvent.event_type.like("content_version.%"),
        )
        .order_by(AuditEvent.created_at)
        .all()
    )
    decisions = [
        (e.event_type, e.entity_id, str(e.actor_user_id), e.details.get("note")) for e in events
    ]
    assert decisions == [
        ("content_version.approved", v1["content_version_id"], owner.user_id, None),
        ("content_version.created", str(v2["content_version_id"]), owner.user_id, None),  # the edit
        ("content_version.rejected", str(v2["content_version_id"]), owner.user_id, "not ready"),
    ]
    assert all(e.created_at is not None for e in events)
    assert (
        client.get(f"/api/reviews/{v1['id']}", headers=owner.headers).json()["status"] == "approved"
    )
