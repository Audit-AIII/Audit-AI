"""Phase 8 audit gap: "invalid schema is rejected" (task 1's checklist, also Phase 4 task 1's
own "the output fails the schema" bullet, never actually wired up until now). Confirmed by
reading the code that `ClaimVerifier.verify()` already turns every `ProviderError` into an
ERROR-verdict `ClaimResult` rather than raising - so the only way `verify_claim` can raise at
all is something unexpected: a bug, or model output malformed in a way the engine's own guards
missed. Before this fix, that would crash the whole HTTP request with a raw 500 instead of
leaving the review in a safe state. One bad claim must not take down the other claims either.

Uses `inkloom_verify.providers.fake.ScriptedProvider` (Member 2's own test double, not a
monkeypatched guess at their internals) to answer extraction deterministically and offline, and
monkeypatches `verify_claim` itself to simulate the unexpected failure - the one thing that
can't come from a real provider reply, by construction.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest
from inkloom_verify.providers.fake import ScriptedProvider

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.models import BrandProfile, BrandSource, Membership, Organisation, SourceVersion, User
from inkloom_api.statuses import BrandSourceStatus

PASSWORD = "correct-horse-battery-staple"

EXTRACTION_REPLY = {
    "statements": [
        {
            "sentence_id": "s1",
            "kind": "factual",
            "claims": [{"text": "The sky is blue.", "source_quote": "The sky is blue."}],
        }
    ]
}


@dataclass
class Fixture:
    org: Organisation
    admin: User
    brand: BrandProfile


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Robustness Org", slug=f"robust-{unique}")
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
    text = "Approved fact."
    db_session.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=text,
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
def test_unexpected_verification_error_does_not_crash_the_request(client, monkeypatch, fixture: Fixture) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    monkeypatch.setattr(
        pipeline, "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("fake", lambda: ScriptedProvider(dict(EXTRACTION_REPLY)))]
        ),
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated unexpected failure, not a ProviderError")

    monkeypatch.setattr(pipeline, "verify_claim", _raise)

    token = _login(client, fixture.admin.email)
    response = client.post(
        "/api/reviews",
        json={"brand_id": str(fixture.brand.id), "text": "The sky is blue."},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 201, response.text  # not a 500 - the request itself succeeded
    body = response.json()
    assert body["status"] == "needs_human_review"  # never silently "completed"
    assert len(body["findings"]) == 1
    finding = body["findings"][0]
    assert finding["verification_status"] == "unverified"  # never contradicted/supported - unknown, honestly
    assert finding["requires_human_review"] is True
    assert "RuntimeError" in finding["explanation"]
    assert "simulated unexpected failure" not in finding["explanation"]  # the raw message is not echoed
