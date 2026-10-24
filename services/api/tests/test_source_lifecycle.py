"""Source lifecycle and InkWatch (docs/backend.md):

1. Withdrawing a source flips every dependent approved item to source_changed.
   -> test_withdraw_flips_every_approved_dependent
2. Items that do not cite the source are unaffected.
   -> test_withdraw_does_not_touch_unrelated_items (and part of test 1)
3. Approval is blocked for a source_changed item until re-reviewed.
   -> test_approval_blocked_for_source_changed_item (also verifies phase6 task 6's "verify it
      covers source_changed")
4. Tenant isolation holds: another organisation's items are never touched.
   -> test_withdraw_never_touches_another_organisations_items
5. Audit events exist for each flipped item.
   -> test_audit_events_exist_for_withdraw_and_each_flip

All forced into stub mode - this tests the lifecycle/audit machinery, not the AI engine.
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
    admin: User
    brand: BrandProfile
    source: BrandSource


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Lifecycle Org", slug=f"lifecycle-{unique}")
    admin = User(email=f"admin-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org, admin])
    db_session.flush()
    db_session.add(Membership(organisation_id=org.id, user_id=admin.id, role="admin", is_active=True))

    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()
    source = BrandSource(brand_profile_id=brand.id, title="Spec", status=BrandSourceStatus.APPROVED.value)
    db_session.add(source)
    db_session.flush()
    text = "Approved fact: the sky is blue."
    db_session.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()

    try:
        yield Fixture(org=org, admin=admin, brand=brand, source=source)
    finally:
        db_session.delete(org)
        db_session.delete(admin)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _submit_and_approve(client, token: str, brand_id, text: str) -> dict:
    """Returns the review dict. Stub mode always needs human review, so one approve call away
    from `approved`."""
    submitted = client.post(
        "/api/reviews", json={"brand_id": str(brand_id), "text": text}, headers=_auth(token)
    )
    assert submitted.status_code == 201, submitted.text
    review = submitted.json()
    approved = client.post(
        f"/api/content-versions/{review['content_version_id']}/approve", headers=_auth(token)
    )
    assert approved.status_code == 201, approved.text
    return review


def _withdraw(client, token: str, brand_id, source_id, status: str = "superseded", reason: str = "drift"):
    return client.post(
        f"/api/brands/{brand_id}/sources/{source_id}/withdraw",
        json={"status": status, "reason": reason},
        headers=_auth(token),
    )


@requires_db
def test_withdraw_flips_every_approved_dependent(client, force_stub_mode, fixture: Fixture) -> None:
    """Stub mode writes a finding with no evidence (category=stub), so it never actually cites
    the real source - approve two reviews, record them as "dependents" via a direct evidence
    link insert to simulate what a real engine run would have produced, then withdraw."""
    token = _login(client, fixture.admin.email)
    review_a = _submit_and_approve(client, token, fixture.brand.id, "Item A content.")
    review_b = _submit_and_approve(client, token, fixture.brand.id, "Item B content.")

    _attach_evidence(fixture.source.id, [review_a["id"], review_b["id"]])

    response = _withdraw(client, token, fixture.brand.id, fixture.source.id)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"]["status"] == "superseded"
    flipped_review_ids = {f["review_id"] for f in body["flipped"]}
    assert flipped_review_ids == {review_a["id"], review_b["id"]}

    for review_id in (review_a["id"], review_b["id"]):
        fetched = client.get(f"/api/reviews/{review_id}", headers=_auth(token))
        assert fetched.json()["status"] == "source_changed"


@requires_db
def test_withdraw_does_not_touch_unrelated_items(client, force_stub_mode, fixture: Fixture) -> None:
    token = _login(client, fixture.admin.email)
    cited_review = _submit_and_approve(client, token, fixture.brand.id, "Cites the source.")
    unrelated_review = _submit_and_approve(client, token, fixture.brand.id, "Never cites anything.")
    _attach_evidence(fixture.source.id, [cited_review["id"]])  # only the first one

    response = _withdraw(client, token, fixture.brand.id, fixture.source.id)
    assert response.status_code == 200
    flipped_review_ids = {f["review_id"] for f in response.json()["flipped"]}
    assert flipped_review_ids == {cited_review["id"]}

    still_approved = client.get(f"/api/reviews/{unrelated_review['id']}", headers=_auth(token))
    assert still_approved.json()["status"] == "approved"  # untouched


@requires_db
def test_approval_blocked_for_source_changed_item(client, force_stub_mode, fixture: Fixture) -> None:
    """Phase 6 task 6: "verify [the approval guard] covers source_changed." It does, via the
    same ensure_decidable check every other non-decidable state uses - no new code needed,
    just verifying it here."""
    token = _login(client, fixture.admin.email)
    review = _submit_and_approve(client, token, fixture.brand.id, "Cites the source.")
    _attach_evidence(fixture.source.id, [review["id"]])
    _withdraw(client, token, fixture.brand.id, fixture.source.id)

    retry = client.post(f"/api/content-versions/{review['content_version_id']}/approve", headers=_auth(token))
    assert retry.status_code == 409
    assert "source_changed" in retry.json()["error"]["message"]


@requires_db
def test_withdraw_never_touches_another_organisations_items(client, force_stub_mode, fixture: Fixture) -> None:
    token = _login(client, fixture.admin.email)
    review = _submit_and_approve(client, token, fixture.brand.id, "Cites the source.")
    _attach_evidence(fixture.source.id, [review["id"]])

    unique = uuid.uuid4().hex[:8]
    from inkloom_api.db import get_session_factory

    db = get_session_factory()()
    other_org = Organisation(name="Other Org", slug=f"other-{unique}")
    other_admin = User(email=f"other-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db.add_all([other_org, other_admin])
    db.flush()
    db.add(Membership(organisation_id=other_org.id, user_id=other_admin.id, role="admin", is_active=True))
    db.commit()
    other_token = _login(client, other_admin.email)

    # The other org's user cannot even see this brand/source - confirms tenant isolation holds
    # at the route level, which is what actually protects the withdraw action.
    denied = _withdraw(client, other_token, fixture.brand.id, fixture.source.id)
    assert denied.status_code == 404

    unchanged = client.get(f"/api/reviews/{review['id']}", headers=_auth(token))
    assert unchanged.json()["status"] == "approved"

    db.delete(other_org)
    db.delete(other_admin)
    db.commit()
    db.close()


@requires_db
def test_audit_events_exist_for_withdraw_and_each_flip(client, force_stub_mode, fixture: Fixture) -> None:
    token = _login(client, fixture.admin.email)
    review = _submit_and_approve(client, token, fixture.brand.id, "Cites the source.")
    _attach_evidence(fixture.source.id, [review["id"]])
    _withdraw(client, token, fixture.brand.id, fixture.source.id, reason="guide v2 replaces this")

    from inkloom_api.db import get_session_factory
    from inkloom_api.models import AuditEvent

    db = get_session_factory()()
    events = (
        db.query(AuditEvent)
        .filter(AuditEvent.organisation_id == fixture.org.id, AuditEvent.event_type.in_(
            ["brand_source.withdrawn", "content_version.source_changed"]
        ))
        .all()
    )
    db.close()
    event_types = {e.event_type for e in events}
    assert event_types == {"brand_source.withdrawn", "content_version.source_changed"}
    flip_event = next(e for e in events if e.event_type == "content_version.source_changed")
    assert flip_event.details["reason"] == "guide v2 replaces this"


def _attach_evidence(source_id: uuid.UUID, review_ids: list[str]) -> None:
    """Stub-mode findings have no real evidence (the engine never ran), so these tests insert
    an EvidenceLink directly to simulate what a real engine run would have produced - this is
    testing the withdraw/dependency-lookup machinery, not evidence validation (that's Phase 4's
    job, already tested separately)."""
    from inkloom_api.db import get_session_factory
    from inkloom_api.models import EvidenceLink, Finding

    db = get_session_factory()()
    for review_id in review_ids:
        finding = db.query(Finding).filter_by(review_id=uuid.UUID(review_id)).one()
        db.add(
            EvidenceLink(
                finding_id=finding.finding_id, source_id=source_id, source_version_id=None,
                quote="the sky is blue", relation="supports",
            )
        )
    db.commit()
    db.close()
