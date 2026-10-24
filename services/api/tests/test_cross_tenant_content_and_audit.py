"""Phase 8 task 1 checklist: "Org A cannot read or mutate org B's review, source, content or
audit records." Reviews and sources are already covered (test_tenant_scoping.py,
test_reviews.py, test_source_lifecycle.py). This file closes the two remaining nouns: content
(content_items/versions, via the history endpoint) and audit (there is no standalone
"GET audit events" route - audit records reach a client only nested inside
`GET /api/content/{id}/history`'s `decisions`, so protecting that endpoint protects both at
once).
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.models import (
    BrandProfile,
    BrandSource,
    Membership,
    Organisation,
    SourceVersion,
    User,
)
from inkloom_api.statuses import BrandSourceStatus

PASSWORD = "correct-horse-battery-staple"


@dataclass
class Fixture:
    org_a: Organisation
    org_b: Organisation
    admin_a: User
    admin_b: User
    brand_a: BrandProfile


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org_a = Organisation(name="Org A", slug=f"content-a-{unique}")
    org_b = Organisation(name="Org B", slug=f"content-b-{unique}")
    admin_a = User(email=f"admin-a-{unique}@example.com", password_hash=hash_password(PASSWORD))
    admin_b = User(email=f"admin-b-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org_a, org_b, admin_a, admin_b])
    db_session.flush()
    db_session.add(
        Membership(organisation_id=org_a.id, user_id=admin_a.id, role="admin", is_active=True)
    )
    db_session.add(
        Membership(organisation_id=org_b.id, user_id=admin_b.id, role="admin", is_active=True)
    )

    brand_a = BrandProfile(organisation_id=org_a.id, name="Brand A")
    db_session.add(brand_a)
    db_session.flush()
    source = BrandSource(
        brand_profile_id=brand_a.id, title="Spec", status=BrandSourceStatus.APPROVED.value
    )
    db_session.add(source)
    db_session.flush()
    text = "Approved fact."
    db_session.add(
        SourceVersion(
            brand_source_id=source.id,
            version_number=1,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()

    try:
        yield Fixture(org_a=org_a, org_b=org_b, admin_a=admin_a, admin_b=admin_b, brand_a=brand_a)
    finally:
        db_session.delete(org_a)
        db_session.delete(org_b)
        db_session.delete(admin_a)
        db_session.delete(admin_b)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@requires_db
def test_org_b_cannot_read_org_as_content_history_or_audit_trail(
    client, force_stub_mode, fixture: Fixture
) -> None:
    token_a = _login(client, fixture.admin_a.email)
    token_b = _login(client, fixture.admin_b.email)

    submitted = client.post(
        "/api/reviews",
        json={"brand_id": str(fixture.brand_a.id), "text": "Some content."},
        headers=_auth(token_a),
    )
    assert submitted.status_code == 201
    content_version_id = submitted.json()["content_version_id"]

    # Approve it, so there's an audit-worthy decision (an ApprovalEvent, surfaced in
    # `decisions`) for org B to try - and fail - to see.
    approved = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(token_a)
    )
    assert approved.status_code == 201

    from inkloom_api.db import get_session_factory
    from inkloom_api.models import ContentVersion

    db = get_session_factory()()
    content_item_id = db.get(ContentVersion, uuid.UUID(content_version_id)).content_item_id
    db.close()

    # Org A can read its own history (sanity check the fixture actually set this up).
    own_history = client.get(f"/api/content/{content_item_id}/history", headers=_auth(token_a))
    assert own_history.status_code == 200
    assert len(own_history.json()["versions"][0]["decisions"]) == 1

    # Org B gets the same safe 404 as a nonexistent content item - never reveals it exists.
    denied = client.get(f"/api/content/{content_item_id}/history", headers=_auth(token_b))
    assert denied.status_code == 404
    assert denied.json()["error"]["code"] == "NOT_FOUND"

    # Org B also cannot mutate it: creating a new version, approving, or requesting changes.
    cannot_edit = client.post(
        f"/api/content/{content_item_id}/versions",
        json={"text": "Hijacked."},
        headers=_auth(token_b),
    )
    assert cannot_edit.status_code == 404

    cannot_approve = client.post(
        f"/api/content-versions/{content_version_id}/approve", headers=_auth(token_b)
    )
    assert cannot_approve.status_code == 404
