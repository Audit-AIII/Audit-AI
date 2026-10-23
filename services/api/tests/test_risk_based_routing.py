"""Phase 9 stretch item 1: risk-based approval routing.

Faking a real high-severity (CONTRADICTED) verdict all the way through the live engine would
need the citation's `passage_id` to exactly match whatever BM25Retriever's chunker actually
assigned to the fixture's source text - an internal of Member 2's retrieval/chunking code this
module should not be reverse-engineering just to drive a severity value. So the approval-guard
tests below take a review to a real decidable state via the normal stub-mode path (real HTTP,
real pipeline), then set `required_reviewer_role` directly via the DB to exercise both routing
branches deterministically - exactly the same thing `engine/pipeline.py` would have written
itself for a real high-severity outcome, just without needing one. The routing *computation*
itself (`_compute_required_reviewer_role`) is tested directly against real `Finding` rows below,
so the one part that actually reads severities is still exercised for real, not assumed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import text

from conftest import requires_db
from inkloom_api.approval_rules import RoutingMismatchError, ensure_role_matches_routing
from inkloom_api.auth.security import hash_password
from inkloom_api.models import (
    BrandProfile,
    BrandSource,
    Finding,
    Membership,
    Organisation,
    Review,
    SourceVersion,
    User,
)
from inkloom_api.statuses import BrandSourceStatus, CheckType, Severity, VerificationStatus

PASSWORD = "correct-horse-battery-staple"


# ---------------------------------------------------------------------------------------------
# Pure predicate - no DB
# ---------------------------------------------------------------------------------------------


def test_ensure_role_matches_routing_allows_the_matching_role() -> None:
    ensure_role_matches_routing("legal_reviewer", "legal_reviewer")  # no raise


def test_ensure_role_matches_routing_admin_always_bypasses() -> None:
    ensure_role_matches_routing("legal_reviewer", "admin")  # no raise
    ensure_role_matches_routing("brand_manager", "admin")  # no raise


def test_ensure_role_matches_routing_none_means_unrouted_anyone_may_decide() -> None:
    ensure_role_matches_routing(None, "approver")  # no raise - legacy/unrouted review


def test_ensure_role_matches_routing_rejects_mismatch() -> None:
    with pytest.raises(RoutingMismatchError) as excinfo:
        ensure_role_matches_routing("legal_reviewer", "brand_manager")
    assert excinfo.value.required_reviewer_role == "legal_reviewer"
    assert excinfo.value.actor_role == "brand_manager"


def test_ensure_role_matches_routing_rejects_plain_approver() -> None:
    """A real, deliberate consequence (see contract/README.md): `approver` holds the APPROVE
    permission but is never itself a valid `required_reviewer_role`, so once a review is
    routed, only the matching specialised role or admin can actually decide it."""
    with pytest.raises(RoutingMismatchError):
        ensure_role_matches_routing("brand_manager", "approver")


# ---------------------------------------------------------------------------------------------
# The routing computation itself, against real Finding rows
# ---------------------------------------------------------------------------------------------


@requires_db
def test_compute_required_reviewer_role_high_severity_routes_to_legal(db_session) -> None:
    from inkloom_api.engine.pipeline import _compute_required_reviewer_role

    org = Organisation(name="Routing Calc Org", slug=f"routing-calc-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    content_version_id = _bare_content_version(db_session, org.id)
    review = Review(content_version_id=content_version_id, status="analysing")
    db_session.add(review)
    db_session.flush()
    db_session.add(_finding(review.id, Severity.LOW))
    db_session.add(_finding(review.id, Severity.HIGH))  # the one that tips it
    db_session.commit()

    assert _compute_required_reviewer_role(db_session, review) == "legal_reviewer"
    # Raw SQL, not db_session.delete(review): Review's `findings` relationship isn't
    # passive_deletes, so an ORM-level delete here tries to null out findings.review_id (NOT
    # NULL) itself instead of letting Postgres's real ON DELETE CASCADE handle it - deleting the
    # organisation this way lets that cascade do its job all the way down.
    db_session.execute(text("DELETE FROM organisations WHERE id = :id"), {"id": org.id})
    db_session.commit()


@requires_db
def test_compute_required_reviewer_role_critical_severity_routes_to_legal(db_session) -> None:
    from inkloom_api.engine.pipeline import _compute_required_reviewer_role

    org = Organisation(name="Routing Calc Org", slug=f"routing-calc-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    content_version_id = _bare_content_version(db_session, org.id)
    review = Review(content_version_id=content_version_id, status="analysing")
    db_session.add(review)
    db_session.flush()
    db_session.add(_finding(review.id, Severity.CRITICAL))
    db_session.commit()

    assert _compute_required_reviewer_role(db_session, review) == "legal_reviewer"
    # Raw SQL, not db_session.delete(review): Review's `findings` relationship isn't
    # passive_deletes, so an ORM-level delete here tries to null out findings.review_id (NOT
    # NULL) itself instead of letting Postgres's real ON DELETE CASCADE handle it - deleting the
    # organisation this way lets that cascade do its job all the way down.
    db_session.execute(text("DELETE FROM organisations WHERE id = :id"), {"id": org.id})
    db_session.commit()


@requires_db
def test_compute_required_reviewer_role_clean_or_low_risk_routes_to_brand_manager(db_session) -> None:
    from inkloom_api.engine.pipeline import _compute_required_reviewer_role

    org = Organisation(name="Routing Calc Org", slug=f"routing-calc-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    content_version_id = _bare_content_version(db_session, org.id)
    review = Review(content_version_id=content_version_id, status="analysing")
    db_session.add(review)
    db_session.flush()
    db_session.add(_finding(review.id, Severity.LOW))
    db_session.add(_finding(review.id, Severity.MEDIUM))
    db_session.commit()

    assert _compute_required_reviewer_role(db_session, review) == "brand_manager"
    # Raw SQL, not db_session.delete(review): Review's `findings` relationship isn't
    # passive_deletes, so an ORM-level delete here tries to null out findings.review_id (NOT
    # NULL) itself instead of letting Postgres's real ON DELETE CASCADE handle it - deleting the
    # organisation this way lets that cascade do its job all the way down.
    db_session.execute(text("DELETE FROM organisations WHERE id = :id"), {"id": org.id})
    db_session.commit()


@requires_db
def test_compute_required_reviewer_role_zero_findings_routes_to_brand_manager(db_session) -> None:
    """A clean review (nothing to flag at all) is still routed somewhere decidable - the
    lightweight one-click path, not left unrouted."""
    from inkloom_api.engine.pipeline import _compute_required_reviewer_role

    org = Organisation(name="Routing Calc Org", slug=f"routing-calc-{uuid.uuid4().hex[:8]}")
    db_session.add(org)
    db_session.flush()
    content_version_id = _bare_content_version(db_session, org.id)
    review = Review(content_version_id=content_version_id, status="analysing")
    db_session.add(review)
    db_session.commit()

    assert _compute_required_reviewer_role(db_session, review) == "brand_manager"
    # Raw SQL, not db_session.delete(review): Review's `findings` relationship isn't
    # passive_deletes, so an ORM-level delete here tries to null out findings.review_id (NOT
    # NULL) itself instead of letting Postgres's real ON DELETE CASCADE handle it - deleting the
    # organisation this way lets that cascade do its job all the way down.
    db_session.execute(text("DELETE FROM organisations WHERE id = :id"), {"id": org.id})
    db_session.commit()


def _bare_content_version(db_session, organisation_id) -> uuid.UUID:
    """Minimal content_item/content_version pair - routing computation only needs a valid
    review_id to attach findings to; it never looks at the content itself."""
    import hashlib

    from inkloom_api.models import ContentItem, ContentVersion

    content_item = ContentItem(organisation_id=organisation_id, title="Routing calc fixture")
    db_session.add(content_item)
    db_session.flush()
    text = "irrelevant"
    content_version = ContentVersion(
        content_item_id=content_item.id, version_number=1, text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )
    db_session.add(content_version)
    db_session.flush()
    return content_version.id


def _finding(review_id: uuid.UUID, severity: Severity) -> Finding:
    return Finding(
        review_id=review_id,
        severity=severity.value,
        original_text="x",
        span_start=0,
        span_end=1,
        check_type=CheckType.RETRIEVAL.value,
        verification_status=VerificationStatus.UNVERIFIED.value,
    )


# ---------------------------------------------------------------------------------------------
# The approval guard: does routing actually gate who may approve, over real HTTP
# ---------------------------------------------------------------------------------------------


@dataclass
class RoutingFixture:
    org: Organisation
    admin: User
    approver: User
    legal_reviewer: User
    brand_manager: User
    reviewer: User
    brand: BrandProfile


@pytest.fixture
def routing_fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Routing Org", slug=f"routing-{unique}")
    admin = User(email=f"admin-{unique}@example.com", password_hash=hash_password(PASSWORD))
    approver = User(email=f"approver-{unique}@example.com", password_hash=hash_password(PASSWORD))
    legal_reviewer = User(email=f"legal-{unique}@example.com", password_hash=hash_password(PASSWORD))
    brand_manager = User(email=f"brandmgr-{unique}@example.com", password_hash=hash_password(PASSWORD))
    reviewer = User(email=f"reviewer-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org, admin, approver, legal_reviewer, brand_manager, reviewer])
    db_session.flush()
    db_session.add_all([
        Membership(organisation_id=org.id, user_id=admin.id, role="admin", is_active=True),
        Membership(organisation_id=org.id, user_id=approver.id, role="approver", is_active=True),
        Membership(organisation_id=org.id, user_id=legal_reviewer.id, role="legal_reviewer", is_active=True),
        Membership(organisation_id=org.id, user_id=brand_manager.id, role="brand_manager", is_active=True),
        Membership(organisation_id=org.id, user_id=reviewer.id, role="reviewer", is_active=True),
    ])

    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()
    source = BrandSource(brand_profile_id=brand.id, title="Spec", status=BrandSourceStatus.APPROVED.value)
    db_session.add(source)
    db_session.flush()
    import hashlib

    text = "Approved fact."
    db_session.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()

    try:
        yield RoutingFixture(
            org=org, admin=admin, approver=approver, legal_reviewer=legal_reviewer,
            brand_manager=brand_manager, reviewer=reviewer, brand=brand,
        )
    finally:
        for user in (admin, approver, legal_reviewer, brand_manager, reviewer):
            db_session.delete(user)
        db_session.delete(org)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _submit(client, token: str, brand_id) -> dict:
    response = client.post(
        "/api/reviews", json={"brand_id": str(brand_id), "text": "Some content."}, headers=_auth(token)
    )
    assert response.status_code == 201, response.text
    return response.json()


def _set_required_reviewer_role(db_session, review_id: str, role: str | None) -> None:
    review = db_session.get(Review, uuid.UUID(review_id))
    review.required_reviewer_role = role
    db_session.commit()


@requires_db
def test_stub_mode_review_is_routed_to_brand_manager_for_real(
    client, force_stub_mode, routing_fixture: RoutingFixture
) -> None:
    """One real, end-to-end check (no DB shortcut) that `_finish` actually writes the routing
    column through the real pipeline: a stub finding is always MEDIUM severity, so it must
    always land on the clean/brand_manager path."""
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    assert review["required_reviewer_role"] == "brand_manager"


@requires_db
def test_brand_manager_can_approve_its_routed_review_legal_reviewer_cannot(
    client, force_stub_mode, routing_fixture: RoutingFixture
) -> None:
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    assert review["required_reviewer_role"] == "brand_manager"  # stub mode's natural routing
    content_version_id = review["content_version_id"]

    legal_token = _login(client, routing_fixture.legal_reviewer.email)
    denied = client.post(f"/api/content-versions/{content_version_id}/approve", headers=_auth(legal_token))
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["code"] == "CONFLICT"
    assert "brand_manager" in denied.json()["error"]["message"]

    brand_manager_token = _login(client, routing_fixture.brand_manager.email)
    approved = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(brand_manager_token)
    )
    assert approved.status_code == 201, approved.text


@requires_db
def test_legal_reviewer_can_approve_a_high_risk_review_brand_manager_cannot(
    client, force_stub_mode, db_session, routing_fixture: RoutingFixture
) -> None:
    """Simulates the high-risk outcome by writing the same column `_finish` would have written
    for a real high/critical finding (see module docstring for why the engine path isn't faked
    end-to-end here) - everything downstream of that column is exercised for real."""
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    _set_required_reviewer_role(db_session, review["id"], "legal_reviewer")
    content_version_id = review["content_version_id"]

    brand_manager_token = _login(client, routing_fixture.brand_manager.email)
    denied = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(brand_manager_token)
    )
    assert denied.status_code == 409, denied.text
    assert "legal_reviewer" in denied.json()["error"]["message"]

    legal_token = _login(client, routing_fixture.legal_reviewer.email)
    approved = client.post(f"/api/content-versions/{content_version_id}/approve", headers=_auth(legal_token))
    assert approved.status_code == 201, approved.text


@requires_db
def test_admin_always_bypasses_routing(
    client, force_stub_mode, db_session, routing_fixture: RoutingFixture
) -> None:
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    _set_required_reviewer_role(db_session, review["id"], "legal_reviewer")
    content_version_id = review["content_version_id"]

    approved = client.post(f"/api/content-versions/{content_version_id}/approve", headers=_auth(token))
    assert approved.status_code == 201, approved.text


@requires_db
def test_plain_approver_is_blocked_by_routing_on_a_routed_review(
    client, force_stub_mode, routing_fixture: RoutingFixture
) -> None:
    """The real, deliberate consequence documented in contract/README.md: `approver` holds the
    APPROVE permission but is never itself a `required_reviewer_role`, so a routed review (which
    is every review that reaches a decidable state - see the brand_manager-default test above)
    is out of reach for a plain approver."""
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    content_version_id = review["content_version_id"]

    approver_token = _login(client, routing_fixture.approver.email)
    denied = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(approver_token)
    )
    assert denied.status_code == 409, denied.text
    assert denied.json()["error"]["code"] == "CONFLICT"


@requires_db
def test_request_changes_is_never_blocked_by_routing(
    client, force_stub_mode, db_session, routing_fixture: RoutingFixture
) -> None:
    """Routing gates *approval* only - rejecting/requesting changes stays safe for any
    REVIEW-permission role regardless of risk tier, same reasoning as staleness and superseded-
    source checks not applying to request-changes either (approval_rules.py)."""
    token = _login(client, routing_fixture.admin.email)
    review = _submit(client, token, routing_fixture.brand.id)
    _set_required_reviewer_role(db_session, review["id"], "legal_reviewer")
    content_version_id = review["content_version_id"]

    reviewer_token = _login(client, routing_fixture.reviewer.email)
    response = client.post(
        f"/api/content-versions/{content_version_id}/request-changes",
        json={"decision": "changes_requested", "note": "please revise"},
        headers=_auth(reviewer_token),
    )
    assert response.status_code == 201, response.text
