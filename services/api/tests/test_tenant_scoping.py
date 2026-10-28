"""Account isolation, against a
real Postgres and the real /api/auth/login + /api/brands/{id}/sources routes.

1. Org A cannot read org B's records.                -> test_org_a_cannot_read_org_bs_brand
2. Changing organisation_id in a query grants nothing.
   -> test_query_string_organisation_override_is_ignored
3. Revoked membership loses access.                    -> test_revoked_membership_loses_access
4. Guessed IDs return a safe 404.                      -> test_guessed_brand_id_returns_safe_404
5. Role escalation attempts are denied.                -> unit-tested in test_permissions.py
   (the one HTTP route this phase ships needs no permission beyond active membership, so there
   is nothing to escalate past here; the permission check itself is tested directly there).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.models import BrandProfile, BrandSource, Membership, Organisation, User

PASSWORD = "correct-horse-battery-staple"


@dataclass
class Tenants:
    org_a: Organisation
    org_b: Organisation
    user_a: User
    user_b: User
    brand_a: BrandProfile
    brand_b: BrandProfile
    source_a: BrandSource
    membership_a: Membership


@pytest.fixture
def tenants(db_session):
    unique = uuid.uuid4().hex[:8]
    org_a = Organisation(name="Org A", slug=f"org-a-{unique}")
    org_b = Organisation(name="Org B", slug=f"org-b-{unique}")
    user_a = User(email=f"user-a-{unique}@example.com", password_hash=hash_password(PASSWORD))
    user_b = User(email=f"user-b-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org_a, org_b, user_a, user_b])
    db_session.flush()

    membership_a = Membership(
        organisation_id=org_a.id, user_id=user_a.id, role="submitter", is_active=True
    )
    membership_b = Membership(
        organisation_id=org_b.id, user_id=user_b.id, role="submitter", is_active=True
    )
    db_session.add_all([membership_a, membership_b])

    brand_a = BrandProfile(organisation_id=org_a.id, name="Brand A")
    brand_b = BrandProfile(organisation_id=org_b.id, name="Brand B")
    db_session.add_all([brand_a, brand_b])
    db_session.flush()

    source_a = BrandSource(brand_profile_id=brand_a.id, title="A spec sheet")
    db_session.add(source_a)
    db_session.commit()

    try:
        yield Tenants(
            org_a=org_a,
            org_b=org_b,
            user_a=user_a,
            user_b=user_b,
            brand_a=brand_a,
            brand_b=brand_b,
            source_a=source_a,
            membership_a=membership_a,
        )
    finally:
        db_session.delete(org_a)  # cascades: membership_a, brand_a, source_a
        db_session.delete(org_b)  # cascades: membership_b, brand_b
        db_session.delete(user_a)
        db_session.delete(user_b)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@requires_db
def test_login_then_read_own_orgs_brand(client, tenants: Tenants) -> None:
    token = _login(client, tenants.user_a.email)
    response = client.get(
        f"/api/brands/{tenants.brand_a.id}/sources", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [str(tenants.source_a.id)]


@requires_db
def test_org_a_cannot_read_org_bs_brand(client, tenants: Tenants) -> None:
    token = _login(client, tenants.user_a.email)
    response = client.get(
        f"/api/brands/{tenants.brand_b.id}/sources", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


@requires_db
def test_query_string_organisation_override_is_ignored(client, tenants: Tenants) -> None:
    """Task 4: organisation_id must come only from the authenticated membership. Even if a
    caller appends a query parameter naming another organisation, the route (which never reads
    such a parameter) keeps using the authenticated org."""
    token = _login(client, tenants.user_a.email)
    response = client.get(
        f"/api/brands/{tenants.brand_a.id}/sources",
        params={"organisation_id": str(tenants.org_b.id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [str(tenants.source_a.id)]


@requires_db
def test_revoked_membership_loses_access(client, db_session, tenants: Tenants) -> None:
    token = _login(client, tenants.user_a.email)  # minted while the membership is active

    tenants.membership_a.is_active = False
    db_session.add(tenants.membership_a)
    db_session.commit()

    response = client.get(
        f"/api/brands/{tenants.brand_a.id}/sources", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


@requires_db
def test_guessed_brand_id_returns_safe_404(client, tenants: Tenants) -> None:
    token = _login(client, tenants.user_a.email)
    response = client.get(
        f"/api/brands/{uuid.uuid4()}/sources", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "exist" not in body["error"]["message"]  # never confirms or denies existence elsewhere


@requires_db
def test_missing_token_is_401(client, tenants: Tenants) -> None:
    response = client.get(f"/api/brands/{tenants.brand_a.id}/sources")
    assert response.status_code == 401


@requires_db
def test_wrong_password_is_401_same_message_as_unknown_email(client, tenants: Tenants) -> None:
    wrong_password = client.post(
        "/api/auth/login", json={"email": tenants.user_a.email, "password": "nope"}
    )
    unknown_email = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "nope"}
    )
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]
