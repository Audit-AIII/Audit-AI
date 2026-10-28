"""Individual-user mode (product decision 2026-10-24). Replaces test_risk_based_routing.py.

InkLoom is now a one-person-per-account app: one email = one private account (organisation), the
user owns all of it, and roles no longer gate anything. What used to be tested here (Phase 9
risk-based routing: high-severity reviews routed to `legal_reviewer`, everything else to
`brand_manager`, enforced at approval) is deliberately switched off. These tests pin the new
behaviour instead:

1. Round 3: reviews are routed (risk_policy.py) - stub mode is medium risk, a real
   CONTRADICTED outcome is high - and a solo owner still signs off (P4);
   -> test_stub_reviews_are_routed_but_a_solo_owner_still_signs_off
   -> test_high_severity_review_is_routed_to_a_reviewer
2. registration still makes the user "admin" (= account owner), and they approve their own
   content and request changes on it;
   -> test_registered_owner_approves_own_content
   -> test_owner_can_request_changes_on_own_content
3. an older review that still carries a routed role no longer restricts approval;
   -> test_legacy_routed_review_is_approvable_by_owner
4. a member with a legacy role name gets the powers of the team role it maps to (Round 3);
   -> test_legacy_role_names_map_to_team_roles
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
def test_stub_reviews_are_routed_but_a_solo_owner_still_signs_off(
    client, force_stub_mode, account_factory
) -> None:
    """Round 3 routing (risk_policy.py): with no AI provider nothing was checked, so the draft is
    medium risk and routed to a reviewer. Alone in their workspace, the owner's approval also
    stands in for that review (DECISIONS_PENDING.md P4), so today's flow keeps working."""
    owner = account_factory("owner")
    review = owner.submit()
    assert review["status"] == "needs_human_review"
    assert (review["risk_level"], review["required_reviewer_role"]) == ("medium", "reviewer")
    assert review["routing_reason"]["code"] == "not_checked"
    assert "approve" in review["allowed_actions"]
    assert _approve(client, owner, review["content_version_id"]).status_code == 201


@requires_db
def test_high_severity_review_is_routed_to_a_reviewer(client, monkeypatch, account_factory) -> None:
    """A real CONTRADICTED verdict (contracts.md section 19): high risk, reviewer first."""
    use_scripted_provider(monkeypatch, CONTRADICTION_RULES)
    owner = account_factory("owner")
    review = owner.submit("Lumen Pods offer up to 24 hours of playback per charge.")
    [finding] = review["findings"]
    assert finding["verification_status"] == "contradicted"
    assert finding["severity"] == "high"
    fetched = client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()
    for body in (review, fetched):
        assert (body["risk_level"], body["required_reviewer_role"]) == ("high", "reviewer")
        assert body["routing_reason"]["code"] == "contradicted_claim"
        assert [t["finding_id"] for t in body["routing_reason"]["triggered_by"]] == [
            finding["finding_id"]
        ]


@requires_db
def test_registered_owner_approves_own_content(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, CONTRADICTION_RULES)
    owner = account_factory("owner")
    assert owner.role == "owner"
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


# (can create drafts, can approve, can upload brand documents) per stored role string.
_LEGACY_ROLE_POWERS = {
    "admin": (True, True, True),  # owner
    "submitter": (True, False, False),  # writer
    "source_manager": (True, False, False),  # writer
    "reviewer": (False, False, False),
    "legal_reviewer": (False, False, False),  # reviewer
    "approver": (False, True, True),
    "brand_manager": (False, True, True),  # approver
}


@requires_db
def test_legacy_role_names_map_to_team_roles(
    client, force_stub_mode, db_session, account_factory
) -> None:
    """Round 3 (docs/governance.md section 5): old rows holding a pre-0014 role name get exactly
    the powers of the team role it maps to (auth/permissions.py `team_role`)."""
    owner = account_factory("owner")
    membership = db_session.query(Membership).filter_by(user_id=uuid.UUID(owner.user_id)).one()
    for legacy_role, (create, approve, upload_docs) in _LEGACY_ROLE_POWERS.items():
        membership.role = "owner"
        db_session.commit()
        review = owner.submit(
            f"Lumen Pods offer up to 12 hours of playback per charge ({legacy_role})."
        )
        membership.role = legacy_role
        db_session.commit()

        submitted = client.post(
            "/api/reviews",
            json={"brand_id": owner.brand_id, "text": f"Another draft ({legacy_role})."},
            headers=owner.headers,
        )
        approved = _approve(client, owner, review["content_version_id"])
        upload = client.post(
            f"/api/brands/{owner.brand_id}/sources",
            data={"title": f"Doc {legacy_role}", "approve": "true"},
            files={"file": ("d.txt", io.BytesIO(b"Warranty: 2 years."), "text/plain")},
            headers=owner.headers,
        )
        assert submitted.status_code == (201 if create else 403), (legacy_role, submitted.text)
        # Allowed by role = anything but 403 (an approver alone can't review, so a stub draft
        # is REVIEW_REQUIRED for them: that is routing, not a permission refusal).
        assert (approved.status_code != 403) is approve, (legacy_role, approved.text)
        assert upload.status_code == (201 if upload_docs else 403), (legacy_role, upload.text)


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
