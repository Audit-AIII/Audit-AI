"""Phase 5 tasks 5, 6 and 8 - the three required tests named explicitly in the phase doc and
confirmed in the Phase 8 audit, not yet covered by any other test file:

1. "Duplicate idempotency key creates one job and one LLM call" (task 6).
2. "Same content in two organisations never shares a cache entry" (task 5 - tenant isolation is
   never optional, not even as a cache optimisation; result_cache.py's own docstring).
3. "A confidential source produces no external call in the log" (task 8).

Each proves the real end-to-end wiring through the actual route, not just the unit underneath
it (those are covered elsewhere: test_fallback_provider.py for the chain itself). A real LLM
call is counted via `inkloom_verify.providers.fake.ScriptedProvider.calls`, Member 2's own test
double - never a monkeypatched guess at their internals.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import pytest
from inkloom_verify.providers.fake import ScriptedProvider

from conftest import requires_db
from inkloom_api.auth.security import hash_password
from inkloom_api.models import (
    BrandProfile,
    BrandSource,
    ExternalCallLog,
    Membership,
    Organisation,
    ResultCache,
    Review,
    SourceVersion,
    User,
)
from inkloom_api.statuses import BrandSourceSensitivity, BrandSourceStatus

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
# No citations needed: NOT_ENOUGH_EVIDENCE skips the citation guard entirely (verification.py),
# so this reply alone is enough to complete one claim's verification in exactly one call.
VERIFICATION_REPLY = {
    "verdict": "NOT_ENOUGH_EVIDENCE",
    "citations": [],
    "rationale": "insufficient context",
}
# An unverified claim also gets one safer-wording call (inkloom_verify.softening); here the model
# declines, so no suggestion is stored.
SOFTENING_REPLY = {
    "status": "needs_human_review",
    "original_text": "",
    "replacement_text": "",
    "citations": [],
    "reason": "Nothing to soften.",
}


def _login(client, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _make_org_with_approved_source(
    db_session, *, label: str, source_text: str, sensitivity: str | None = None
):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name=f"{label} Org", slug=f"{label.lower()}-{unique}")
    admin = User(
        email=f"{label.lower()}-{unique}@example.com", password_hash=hash_password(PASSWORD)
    )
    db_session.add_all([org, admin])
    db_session.flush()
    db_session.add(
        Membership(organisation_id=org.id, user_id=admin.id, role="admin", is_active=True)
    )

    brand = BrandProfile(organisation_id=org.id, name="Brand")
    db_session.add(brand)
    db_session.flush()
    kwargs = {"sensitivity": sensitivity} if sensitivity else {}
    source = BrandSource(
        brand_profile_id=brand.id, title="Spec", status=BrandSourceStatus.APPROVED.value, **kwargs
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(
        SourceVersion(
            brand_source_id=source.id,
            version_number=1,
            text=source_text,
            text_sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        )
    )
    db_session.commit()
    return org, admin, brand


# ---------------------------------------------------------------------------------------------
# Task 6: duplicate idempotency key -> one job, one LLM call
# ---------------------------------------------------------------------------------------------


@dataclass
class IdemFixture:
    org: Organisation
    admin: User
    brand: BrandProfile


@pytest.fixture
def idem_fixture(db_session):
    org, admin, brand = _make_org_with_approved_source(
        db_session,
        label="Idem",
        source_text="The sky is blue on a clear day, according to the approved spec.",
    )
    try:
        yield IdemFixture(org=org, admin=admin, brand=brand)
    finally:
        db_session.delete(org)
        db_session.delete(admin)
        db_session.commit()


@requires_db
def test_duplicate_idempotency_key_creates_one_job_and_one_llm_call(
    client, monkeypatch, db_session, idem_fixture: IdemFixture
) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    scripted = ScriptedProvider(
        dict(EXTRACTION_REPLY), dict(VERIFICATION_REPLY), dict(SOFTENING_REPLY)
    )
    monkeypatch.setattr(
        pipeline,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("fake", lambda: scripted)], on_attempt=on_attempt
        ),
    )

    token = _login(client, idem_fixture.admin.email)
    body = {"brand_id": str(idem_fixture.brand.id), "text": "The sky is blue."}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "fixed-key-123"}

    first = client.post("/api/reviews", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert (
        len(scripted.calls) == 3
    )  # one extraction call, one verification call, one softening call

    second = client.post("/api/reviews", json=body, headers=headers)
    assert second.status_code == 201, second.text
    assert second.json() == first.json()  # byte-identical replay, not a second analysis
    assert len(scripted.calls) == 3  # unchanged - the second request made no LLM call at all

    review_count = (
        db_session.query(Review)
        .filter(Review.content_version_id == uuid.UUID(first.json()["content_version_id"]))
        .count()
    )
    assert review_count == 1  # one job, not two


# ---------------------------------------------------------------------------------------------
# Task 5: identical content in two organisations never shares a cache entry
# ---------------------------------------------------------------------------------------------


@dataclass
class CrossOrgFixture:
    org_a: Organisation
    admin_a: User
    brand_a: BrandProfile
    org_b: Organisation
    admin_b: User
    brand_b: BrandProfile


@pytest.fixture
def cross_org_fixture(db_session):
    shared_source_text = "The sky is blue on a clear day, byte-identical across both organisations."
    org_a, admin_a, brand_a = _make_org_with_approved_source(
        db_session, label="CacheA", source_text=shared_source_text
    )
    org_b, admin_b, brand_b = _make_org_with_approved_source(
        db_session, label="CacheB", source_text=shared_source_text
    )
    try:
        yield CrossOrgFixture(
            org_a=org_a,
            admin_a=admin_a,
            brand_a=brand_a,
            org_b=org_b,
            admin_b=admin_b,
            brand_b=brand_b,
        )
    finally:
        db_session.delete(org_a)
        db_session.delete(admin_a)
        db_session.delete(org_b)
        db_session.delete(admin_b)
        db_session.commit()


@requires_db
def test_same_content_in_two_organisations_never_shares_a_cache_entry(
    client, monkeypatch, db_session, cross_org_fixture: CrossOrgFixture
) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    # Six replies: a full extraction+verification+softening set for each organisation's own
    # analysis. If org B's request could be served from org A's cache, it would never consume
    # replies 4-6, and ScriptedProvider would still have them left over at the end of the test.
    scripted = ScriptedProvider(
        dict(EXTRACTION_REPLY),
        dict(VERIFICATION_REPLY),
        dict(SOFTENING_REPLY),
        dict(EXTRACTION_REPLY),
        dict(VERIFICATION_REPLY),
        dict(SOFTENING_REPLY),
    )
    monkeypatch.setattr(
        pipeline,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("fake", lambda: scripted)], on_attempt=on_attempt
        ),
    )

    same_text = "The sky is blue."

    token_a = _login(client, cross_org_fixture.admin_a.email)
    response_a = client.post(
        "/api/reviews",
        json={"brand_id": str(cross_org_fixture.brand_a.id), "text": same_text},
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert response_a.status_code == 201, response_a.text
    assert len(scripted.calls) == 3

    token_b = _login(client, cross_org_fixture.admin_b.email)
    response_b = client.post(
        "/api/reviews",
        json={"brand_id": str(cross_org_fixture.brand_b.id), "text": same_text},
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert response_b.status_code == 201, response_b.text
    # Byte-identical content, byte-identical source text, but a DIFFERENT organisation: org B's
    # request must still hit the provider for real, not replay org A's cached result.
    assert len(scripted.calls) == 6

    body_a, body_b = response_a.json(), response_b.json()
    assert body_a["id"] != body_b["id"]
    assert body_a["served_from_cache"] is False
    assert body_b["served_from_cache"] is False

    cache_rows = (
        db_session.query(ResultCache)
        .filter(ResultCache.review_id.in_([uuid.UUID(body_a["id"]), uuid.UUID(body_b["id"])]))
        .all()
    )
    assert len(cache_rows) == 2
    assert cache_rows[0].cache_key != cache_rows[1].cache_key


# ---------------------------------------------------------------------------------------------
# Task 8: a confidential source produces no external call in the log
# ---------------------------------------------------------------------------------------------


@dataclass
class ConfidentialFixture:
    org: Organisation
    admin: User
    brand: BrandProfile


@pytest.fixture
def confidential_fixture(db_session):
    org, admin, brand = _make_org_with_approved_source(
        db_session,
        label="Confidential",
        source_text="Secret internal fact.",
        sensitivity=BrandSourceSensitivity.CONFIDENTIAL.value,
    )
    try:
        yield ConfidentialFixture(org=org, admin=admin, brand=brand)
    finally:
        db_session.delete(org)
        db_session.delete(admin)
        db_session.commit()


@requires_db
def test_confidential_source_produces_no_external_call_in_the_log(
    client, monkeypatch, force_stub_mode, db_session, confidential_fixture: ConfidentialFixture
) -> None:
    import inkloom_api.engine.provider as provider_module

    def _must_never_be_called():
        raise AssertionError(
            "a cloud provider builder must never even be constructed for confidential content"
        )

    # Not merely "fails" - literally never in the list FallbackProvider is given, matching
    # provider.py's own docstring. force_stub_mode also leaves Ollama (the one builder still
    # offered) unconfigured, so this review takes the existing confidential-stub path.
    monkeypatch.setattr(
        provider_module,
        "_CLOUD_BUILDERS",
        [
            ("gemini", _must_never_be_called),
            ("groq", _must_never_be_called),
            ("openrouter", _must_never_be_called),
        ],
    )

    token = _login(client, confidential_fixture.admin.email)
    response = client.post(
        "/api/reviews",
        json={"brand_id": str(confidential_fixture.brand.id), "text": "Some content to check."},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["engine"]["provider"] == "stub-unconfigured"
    assert "confidential" in body["findings"][0]["explanation"]

    call_count = (
        db_session.query(ExternalCallLog)
        .filter(ExternalCallLog.organisation_id == confidential_fixture.org.id)
        .count()
    )
    assert call_count == 0
