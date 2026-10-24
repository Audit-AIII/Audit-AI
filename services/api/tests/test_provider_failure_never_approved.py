"""Phase 8 task 1 checklist: "Provider 429, timeout, invalid JSON and all-providers-down never
produce an approved state." Each failure mode is already unit-tested at the provider-adapter
level (test_fallback_provider.py: falls through / exhausts correctly for each). This file ties
that to the approval guard end to end, through the real route: a provider that is configured
but fails on every call (not merely *unconfigured*, which is the separate stub-mode path other
tests exercise) must land the review in `failed`, and `failed` must never be approvable.

A fake, always-failing `LLMProvider` stands in for "configured but down" - this is deliberately
not a real network call (slow, flaky, and Phase 5's own mocked tests already prove each
individual error code's handling); this test's job is only the end-to-end wiring.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest
from inkloom_verify.providers.base import (
    JsonCompletion,
    JsonCompletionRequest,
    ProviderRateLimitError,
)

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


class _AlwaysRateLimitedProvider:
    """Configured (satisfies the LLMProvider protocol), but every call fails with 429 - the
    same error code the real OpenRouter `:free` tier hit (CONTRACTS.md), standing in for any of
    the checklist's named failure modes, which FallbackProvider treats identically."""

    name = "always-429"

    def sampling(self) -> dict:
        return {}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        raise ProviderRateLimitError("rate limited on every attempt")


@dataclass
class Fixture:
    org: Organisation
    admin: User
    brand: BrandProfile


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Failure Org", slug=f"failure-{unique}")
    admin = User(email=f"admin-{unique}@example.com", password_hash=hash_password(PASSWORD))
    db_session.add_all([org, admin])
    db_session.flush()
    db_session.add(
        Membership(organisation_id=org.id, user_id=admin.id, role="admin", is_active=True)
    )

    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()
    source = BrandSource(
        brand_profile_id=brand.id, title="Spec", status=BrandSourceStatus.APPROVED.value
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
        yield Fixture(org=org, admin=admin, brand=brand)
    finally:
        db_session.delete(org)
        db_session.delete(admin)
        db_session.commit()


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@requires_db
def test_all_providers_failing_never_produces_an_approved_state(
    client, monkeypatch, fixture: Fixture
) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    monkeypatch.setattr(
        pipeline,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("always-429", lambda: _AlwaysRateLimitedProvider())]
        ),
    )

    token = _login(client, fixture.admin.email)
    submitted = client.post(
        "/api/reviews",
        json={"brand_id": str(fixture.brand.id), "text": "The sky is blue."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert submitted.status_code == 201, submitted.text
    review = submitted.json()
    assert review["status"] == "failed"  # never completed, never needs_human_review
    assert review["findings"] == []
    assert "all providers failed" in review["error_summary"]

    denied = client.post(
        f"/api/content-versions/{review['content_version_id']}/approve",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert denied.status_code == 409
    assert denied.json()["error"]["code"] == "CONFLICT"
