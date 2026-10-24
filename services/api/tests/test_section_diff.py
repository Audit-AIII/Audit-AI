"""Phase 7 task 4: the automatic section-diff narrows withdraw's blanket flip to only the
dependents whose *cited* section actually changed.

Empirically verified first (not guessed): with two ~250-word sections separated by a blank
line, chunk_document's token-window strategy produces one passage covering the first section
(with overlap into the second) and one passage covering the second section alone. Editing only
the first section's words changes the first passage's hash but leaves the second passage's text
- and therefore its hash - byte-identical, even though its character offsets shift. That's
exactly the scenario this test exercises: two dependents citing the changed section (both
should flip), one dependent citing the unchanged section (should not).
"""

from __future__ import annotations

import hashlib
import io
import uuid
from dataclasses import dataclass

import pytest
from inkloom_verify.chunking import ChunkingConfig, chunk_document
from inkloom_verify.schemas import ReferenceDocument

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


def _section(label: str, n: int = 60) -> str:
    return ". ".join(f"{label} fact number {i} is true" for i in range(n)) + "."


ALPHA = _section("Alpha")
BETA = _section("Beta")
V1_TEXT = ALPHA + "\n\n" + BETA
V2_TEXT = _section("AlphaChanged") + "\n\n" + BETA  # beta untouched, same as the empirical check


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Fixture:
    org: Organisation
    admin: User
    brand: BrandProfile
    source: BrandSource


@pytest.fixture
def fixture(db_session):
    unique = uuid.uuid4().hex[:8]
    org = Organisation(name="Diff Org", slug=f"diff-{unique}")
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
        brand_profile_id=brand.id, title="Guide", status=BrandSourceStatus.APPROVED.value
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(
        SourceVersion(
            brand_source_id=source.id,
            version_number=1,
            text=V1_TEXT,
            text_sha256=_sha256(V1_TEXT),
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


def _attach_evidence(source_id: uuid.UUID, review_id: str, span, quote: str) -> None:
    from inkloom_api.db import get_session_factory
    from inkloom_api.models import EvidenceLink, Finding
    from inkloom_api.section_diff import section_hash_for_span

    db = get_session_factory()()
    finding = db.query(Finding).filter_by(review_id=uuid.UUID(review_id)).one()
    doc = ReferenceDocument(doc_id=str(source_id), text=V1_TEXT, text_sha256=_sha256(V1_TEXT))
    db.add(
        EvidenceLink(
            finding_id=finding.finding_id,
            source_id=source_id,
            source_version_id=None,
            quote=quote,
            relation="supports",
            cited_section_hash=section_hash_for_span(doc, span),
        )
    )
    db.commit()
    db.close()


@requires_db
def test_new_version_only_flips_dependents_whose_section_changed(
    client, force_stub_mode, fixture: Fixture
) -> None:
    v1_passages = chunk_document(
        ReferenceDocument(
            doc_id=str(fixture.source.id), text=V1_TEXT, text_sha256=_sha256(V1_TEXT)
        ),
        ChunkingConfig(),
    )
    assert len(v1_passages) == 3  # matches the empirical check this test's design relies on
    alpha_passage, _, beta_passage = v1_passages

    token = _login(client, fixture.admin.email)

    # Two dependents cite the section that is about to change (Alpha); one cites the section
    # that will stay byte-identical (Beta). Matches the phase doc's own demo framing ("watch
    # three approved items flip") while also proving the narrowing: only 2 of the 3 should.
    review_a1 = _submit_and_approve(client, token, fixture.brand.id, "Item citing alpha, one.")
    review_a2 = _submit_and_approve(client, token, fixture.brand.id, "Item citing alpha, two.")
    review_b = _submit_and_approve(client, token, fixture.brand.id, "Item citing beta.")
    _attach_evidence(fixture.source.id, review_a1["id"], alpha_passage.span, alpha_passage.text)
    _attach_evidence(fixture.source.id, review_a2["id"], alpha_passage.span, alpha_passage.text)
    _attach_evidence(fixture.source.id, review_b["id"], beta_passage.span, beta_passage.text)

    response = client.post(
        f"/api/brands/{fixture.brand.id}/sources/{fixture.source.id}/versions",
        headers=_auth(token),
        files={"file": ("guide-v2.txt", io.BytesIO(V2_TEXT.encode("utf-8")), "text/plain")},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version_number"] == 2
    flipped_ids = {f["review_id"] for f in body["flipped"]}
    assert flipped_ids == {review_a1["id"], review_a2["id"]}

    for review_id, expected in (
        (review_a1["id"], "source_changed"),
        (review_a2["id"], "source_changed"),
        (review_b["id"], "approved"),
    ):
        fetched = client.get(f"/api/reviews/{review_id}", headers=_auth(token))
        assert fetched.json()["status"] == expected
