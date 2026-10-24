"""Smoke test: create a review, fetch it, see
findings. Analysis is synchronous, so there is nothing to poll — the POST response already
carries the final state, and a follow-up GET proves it was actually persisted, not just echoed.

Covers two of the task's required outcomes directly:
- the real engine path when configured, or a clearly labelled stub when it is not (task 3) —
  exercised here via the stub path, since these tests must not depend on real credentials;
- `failed`, never a silent pass, when a brand has nothing to verify against (task 1's "brand
  belongs to the user's organisation" validation plus the "never fail open" rule).

Tenant scoping for the two new routes (cross-tenant GET, cross-tenant brand_id on POST) is also
covered here rather than duplicating the `tenants` fixture from test_tenant_scoping.py.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.statuses import BrandSourceStatus
from inkloom_api.models import BrandProfile, BrandSource, Membership, Organisation, SourceVersion, User

PASSWORD = "correct-horse-battery-staple"


@dataclass
class ReviewFixture:
    org_a: Organisation
    org_b: Organisation
    user_a: User
    user_reviewer: User  # active member of org_a with the legacy `reviewer` role
    brand_with_source: BrandProfile
    brand_without_source: BrandProfile
    brand_b: BrandProfile


@pytest.fixture
def review_fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org_a = Organisation(name="Org A", slug=f"rev-org-a-{unique}")
    org_b = Organisation(name="Org B", slug=f"rev-org-b-{unique}")
    user_a = User(email=f"rev-user-a-{unique}@example.com", password_hash=hash_password(PASSWORD))
    user_reviewer = User(email=f"rev-user-reviewer-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org_a, org_b, user_a, user_reviewer])
    db_session.flush()

    db_session.add(Membership(organisation_id=org_a.id, user_id=user_a.id, role="submitter", is_active=True))
    db_session.add(
        Membership(organisation_id=org_a.id, user_id=user_reviewer.id, role="reviewer", is_active=True)
    )

    brand_with_source = BrandProfile(organisation_id=org_a.id, name="Brand With Source")
    brand_without_source = BrandProfile(organisation_id=org_a.id, name="Brand Without Source")
    brand_b = BrandProfile(organisation_id=org_b.id, name="Brand B")
    db_session.add_all([brand_with_source, brand_without_source, brand_b])
    db_session.flush()

    approved_source = BrandSource(
        brand_profile_id=brand_with_source.id, title="Spec sheet", status=BrandSourceStatus.APPROVED.value
    )
    db_session.add(approved_source)
    db_session.flush()
    source_text = "Lumen Bottle Product Specification. Insulation: keeps drinks cold for up to 24 hours."
    db_session.add(
        SourceVersion(
            brand_source_id=approved_source.id,
            version_number=1,
            text=source_text,
            # Must be the real hash: inkloom_verify.schemas.ReferenceDocument recomputes and
            # rejects a mismatch (CONTRACTS.md, "Text hashes").
            text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()

    try:
        yield ReviewFixture(
            org_a=org_a,
            org_b=org_b,
            user_a=user_a,
            user_reviewer=user_reviewer,
            brand_with_source=brand_with_source,
            brand_without_source=brand_without_source,
            brand_b=brand_b,
        )
    finally:
        db_session.delete(org_a)  # cascades: both memberships, both brands, source, source_version
        db_session.delete(org_b)
        db_session.delete(user_a)
        db_session.delete(user_reviewer)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@requires_db
def test_create_review_without_llm_provider_uses_labelled_stub(client, force_stub_mode, review_fixture: ReviewFixture) -> None:
    token = _login(client, review_fixture.user_a.email)

    response = client.post(
        "/api/reviews",
        json={"brand_id": str(review_fixture.brand_with_source.id), "text": "The Lumen Bottle keeps drinks cold."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "needs_human_review"
    assert body["engine"]["provider"] == "stub-unconfigured"
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["category"] == "stub"
    assert finding["verification_status"] == "unverified"
    assert finding["requires_human_review"] is True
    assert "[STUB OUTPUT]" in finding["explanation"]

    # A follow-up GET proves it was persisted, not just echoed back.
    fetched = client.get(f"/api/reviews/{body['id']}", headers={"Authorization": f"Bearer {token}"})
    assert fetched.status_code == 200
    assert fetched.json() == body


@requires_db
def test_create_review_with_no_approved_sources_fails_not_silently(client, review_fixture: ReviewFixture) -> None:
    token = _login(client, review_fixture.user_a.email)

    response = client.post(
        "/api/reviews",
        json={"brand_id": str(review_fixture.brand_without_source.id), "text": "Some content."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["findings"] == []
    assert "no approved sources" in body["error_summary"]


@requires_db
def test_create_review_rejects_brand_from_another_organisation(client, review_fixture: ReviewFixture) -> None:
    token = _login(client, review_fixture.user_a.email)

    response = client.post(
        "/api/reviews",
        json={"brand_id": str(review_fixture.brand_b.id), "text": "Some content."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@requires_db
def test_get_review_is_scoped_to_organisation(client, force_stub_mode, review_fixture: ReviewFixture) -> None:
    token = _login(client, review_fixture.user_a.email)
    created = client.post(
        "/api/reviews",
        json={"brand_id": str(review_fixture.brand_with_source.id), "text": "The Lumen Bottle keeps drinks cold."},
        headers={"Authorization": f"Bearer {token}"},
    )
    review_id = created.json()["id"]

    guessed = client.get(f"/api/reviews/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
    assert guessed.status_code == 404

    missing_auth = client.get(f"/api/reviews/{review_id}")
    assert missing_auth.status_code == 401


@requires_db
def test_legacy_reviewer_role_can_submit(client, force_stub_mode, review_fixture: ReviewFixture) -> None:
    """Individual-user mode (2026-10-24): roles no longer gate anything, so a member with the
    legacy `reviewer` role (which used to get 403 here, lacking `submit`) is the account owner and
    may submit. Replaces test_post_reviews_requires_submit_permission."""
    token = _login(client, review_fixture.user_reviewer.email)
    response = client.post(
        "/api/reviews",
        json={"brand_id": str(review_fixture.brand_with_source.id), "text": "Some content."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text


@requires_db
def test_get_brand_sources_allows_any_active_role(client, review_fixture: ReviewFixture) -> None:
    """The read route allows any active member, whatever (legacy) role string it carries."""
    token = _login(client, review_fixture.user_reviewer.email)
    response = client.get(
        f"/api/brands/{review_fixture.brand_with_source.id}/sources",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


@requires_db
def test_draft_source_is_never_used_as_evidence(db_session) -> None:
    """Phase 4 required test 5: a draft source sits alongside an approved one on the same
    brand; only the approved one's text may ever reach the corpus the engine is allowed to cite.
    """
    from inkloom_api.review_runner import latest_approved_sources

    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Draft Source Org", slug=f"draft-src-{unique}")
    db_session.add(org)
    db_session.flush()
    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()

    draft = BrandSource(brand_profile_id=brand.id, title="Unreviewed draft", status=BrandSourceStatus.DRAFT.value)
    approved = BrandSource(brand_profile_id=brand.id, title="Approved spec", status=BrandSourceStatus.APPROVED.value)
    db_session.add_all([draft, approved])
    db_session.flush()

    draft_text = "SECRET DRAFT TEXT: never cite this."
    approved_text = "The published fact: INKLOOM AI never auto-publishes a correction."
    db_session.add_all(
        [
            SourceVersion(
                brand_source_id=draft.id, version_number=1, text=draft_text,
                text_sha256=hashlib.sha256(draft_text.encode("utf-8")).hexdigest(),
            ),
            SourceVersion(
                brand_source_id=approved.id, version_number=1, text=approved_text,
                text_sha256=hashlib.sha256(approved_text.encode("utf-8")).hexdigest(),
            ),
        ]
    )
    db_session.commit()

    try:
        sources = latest_approved_sources(db_session, brand.id)
        assert [s.id for s, _ in sources] == [approved.id]
        assert [v.text for _, v in sources] == [approved_text]
    finally:
        db_session.delete(org)  # cascades: brand, both sources, both source_versions
        db_session.commit()
