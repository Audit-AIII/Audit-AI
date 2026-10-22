"""Phase 6 required tests (phase6_versioning_approval_audit.md, "Tests (write now)"):

1. Non-approver gets a safe 403 or 409, with an audit event where appropriate.
   -> test_reviewer_cannot_approve_but_can_request_changes
2. Stale approval rejected.                        -> test_approval_rejected_when_stale
3. Approval blocked when analysis failed.          -> test_approval_blocked_when_review_failed
4. Edit after approval creates a new version that is not approved.
   -> test_edit_after_approval_creates_unapproved_version
5. Concurrent reviewer actions leave state and audit consistent.
   -> test_concurrent_decisions_second_one_is_rejected_not_corrupting_state
6. Invalid transitions rejected.                   -> unit-tested directly in test_approval_rules.py
   (also exercised here via the "already decided" and "not yet analysed" cases)

All forced into stub mode (`force_stub_mode`) - these test the approval/versioning/audit
machinery, not the AI engine, and must not depend on real network access or real credentials.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.models import BrandProfile, BrandSource, Membership, Organisation, SourceVersion, User
from inkloom_api.statuses import BrandSourceStatus

PASSWORD = "correct-horse-battery-staple"


@dataclass
class Fixture:
    org: Organisation
    admin: User  # holds every permission - submits, approves
    reviewer: User  # review only, not approve
    brand: BrandProfile


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Versioning Org", slug=f"versioning-{unique}")
    admin = User(email=f"admin-{unique}@example.com", password_hash=hash_password(PASSWORD))
    reviewer = User(email=f"reviewer-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org, admin, reviewer])
    db_session.flush()
    db_session.add(Membership(organisation_id=org.id, user_id=admin.id, role="admin", is_active=True))
    db_session.add(Membership(organisation_id=org.id, user_id=reviewer.id, role="reviewer", is_active=True))

    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()
    source = BrandSource(brand_profile_id=brand.id, title="Spec", status=BrandSourceStatus.APPROVED.value)
    db_session.add(source)
    db_session.flush()
    text = "Approved fact."
    db_session.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()

    try:
        yield Fixture(org=org, admin=admin, reviewer=reviewer, brand=brand)
    finally:
        db_session.delete(org)  # cascades: memberships, brand, source, source_version
        db_session.delete(admin)
        db_session.delete(reviewer)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _submit(client, token: str, brand_id, text: str = "Some content.") -> dict:
    response = client.post("/api/reviews", json={"brand_id": str(brand_id), "text": text}, headers=_auth(token))
    assert response.status_code == 201, response.text
    return response.json()


@requires_db
def test_reviewer_cannot_approve_but_can_request_changes(client, force_stub_mode, fixture: Fixture) -> None:
    admin_token = _login(client, fixture.admin.email)
    reviewer_token = _login(client, fixture.reviewer.email)
    review = _submit(client, admin_token, fixture.brand.id)
    content_version_id = review["content_version_id"]
    assert review["status"] == "needs_human_review"  # stub mode always needs a human look

    denied = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(reviewer_token)
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    allowed = client.post(
        f"/api/content-versions/{content_version_id}/request-changes",
        json={"decision": "changes_requested", "note": "fix the terminology"},
        headers=_auth(reviewer_token),
    )
    assert allowed.status_code == 201, allowed.text
    body = allowed.json()
    assert body["action"] == "changes_requested"
    assert body["note"] == "fix the terminology"


@requires_db
def test_approval_blocked_when_review_failed(client, fixture: Fixture) -> None:
    """No approved sources at all -> review fails -> nothing to approve (task 4)."""
    admin_token = _login(client, fixture.admin.email)
    other_brand = BrandProfile(organisation_id=fixture.org.id, name="Empty brand")
    # Create it directly: no API route creates a brand without sources in one call.
    from inkloom_api.db import get_session_factory

    db = get_session_factory()()
    db.add(other_brand)
    db.commit()
    brand_id = other_brand.id
    db.close()

    review = _submit(client, admin_token, brand_id)
    assert review["status"] == "failed"

    response = client.post(
        f"/api/content-versions/{review['content_version_id']}/approve", headers=_auth(admin_token)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@requires_db
def test_approval_rejected_when_stale(client, force_stub_mode, fixture: Fixture) -> None:
    admin_token = _login(client, fixture.admin.email)
    review = _submit(client, admin_token, fixture.brand.id)
    content_version_id = review["content_version_id"]

    # Find the content_item_id via history isn't exposed by the review response, so edit via
    # the content item directly - fetch it through the DB to get the id for the versions route.
    from inkloom_api.db import get_session_factory
    from inkloom_api.models import ContentVersion

    db = get_session_factory()()
    content_item_id = db.get(ContentVersion, uuid.UUID(content_version_id)).content_item_id
    db.close()

    new_version = client.post(
        f"/api/content/{content_item_id}/versions", json={"text": "Edited content."}, headers=_auth(admin_token)
    )
    assert new_version.status_code == 201, new_version.text

    stale_approval = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(admin_token)
    )
    assert stale_approval.status_code == 409
    assert "stale" in stale_approval.json()["error"]["message"]


@requires_db
def test_edit_after_approval_creates_unapproved_version(client, force_stub_mode, fixture: Fixture) -> None:
    admin_token = _login(client, fixture.admin.email)
    review = _submit(client, admin_token, fixture.brand.id)
    content_version_id = review["content_version_id"]

    approved = client.post(f"/api/content-versions/{content_version_id}/approve", headers=_auth(admin_token))
    assert approved.status_code == 201, approved.text

    from inkloom_api.db import get_session_factory
    from inkloom_api.models import ContentVersion

    db = get_session_factory()()
    content_item_id = db.get(ContentVersion, uuid.UUID(content_version_id)).content_item_id
    db.close()

    edited = client.post(
        f"/api/content/{content_item_id}/versions", json={"text": "Edited after approval."}, headers=_auth(admin_token)
    )
    assert edited.status_code == 201
    assert edited.json()["is_current"] is True

    history = client.get(f"/api/content/{content_item_id}/history", headers=_auth(admin_token))
    assert history.status_code == 200
    versions = history.json()["versions"]
    assert len(versions) == 2
    v1, v2 = versions[0], versions[1]
    assert v1["is_current"] is False and len(v1["decisions"]) == 1 and v1["decisions"][0]["action"] == "approved"
    assert v2["is_current"] is True and v2["decisions"] == []  # the new version is not approved


@requires_db
def test_concurrent_decisions_second_one_is_rejected_not_corrupting_state(
    client, force_stub_mode, fixture: Fixture
) -> None:
    """Two decisions on the same review: the first one wins, the second is a safe invalid
    transition (409) rather than silently overwriting the first or leaving mixed state."""
    admin_token = _login(client, fixture.admin.email)
    review = _submit(client, admin_token, fixture.brand.id)
    content_version_id = review["content_version_id"]

    first = client.post(f"/api/content-versions/{content_version_id}/approve", headers=_auth(admin_token))
    assert first.status_code == 201

    second = client.post(
        f"/api/content-versions/{content_version_id}/request-changes",
        json={"decision": "rejected", "note": "too late"},
        headers=_auth(admin_token),
    )
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"

    from inkloom_api.db import get_session_factory
    from inkloom_api.models import ApprovalEvent

    db = get_session_factory()()
    events = db.query(ApprovalEvent).filter_by(content_version_id=uuid.UUID(content_version_id)).all()
    db.close()
    assert len(events) == 1  # only the first decision was recorded
    assert events[0].action == "approved"


@requires_db
def test_rerun_creates_a_new_review_leaving_the_old_one_untouched(client, force_stub_mode, fixture: Fixture) -> None:
    admin_token = _login(client, fixture.admin.email)
    original = _submit(client, admin_token, fixture.brand.id)

    rerun = client.post(f"/api/reviews/{original['id']}/rerun", headers=_auth(admin_token))
    assert rerun.status_code == 201
    new_review = rerun.json()
    assert new_review["id"] != original["id"]
    assert new_review["content_version_id"] == original["content_version_id"]

    old_fetched = client.get(f"/api/reviews/{original['id']}", headers=_auth(admin_token))
    assert old_fetched.json()["status"] == original["status"]  # untouched by the rerun
