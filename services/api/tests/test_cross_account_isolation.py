"""Cross-account isolation in individual-user mode: user B can never see or touch user A's data.

Each account is one person's private organisation, created through the real register route.
Every attempt by B on A's ids must be a 404 that is indistinguishable from a random id (same
code, same message), must not change A's data, and must not create anything in either account.

1. B cannot list A's sources, read A's review/history, or see A's brands in GET /api/brands.
   -> test_b_cannot_list_or_read_a
2. B cannot review against A's brand (pasted text or upload) - and nothing is created.
   -> test_b_cannot_review_against_a_brand
3. B cannot approve, request changes on, re-run, or add a version to A's content.
   -> test_b_cannot_decide_or_edit_a_content
4. B cannot upload to, approve, withdraw or version A's sources.
   -> test_b_cannot_upload_or_change_a_sources
"""

from __future__ import annotations

import io
import uuid

from conftest import requires_db
from inkloom_api.models import ApprovalEvent, AuditEvent, BrandSource, ContentItem


def _file(text: str = "Battery: 99 hours.") -> dict:
    return {"file": ("facts.txt", io.BytesIO(text.encode("utf-8")), "text/plain")}


def _assert_same_404(response, random_response) -> None:
    """The response to A's real id must be identical to a random id's: no existence leak."""
    assert response.status_code == 404, response.text
    assert random_response.status_code == 404, random_response.text
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert response.json()["error"]["message"] == random_response.json()["error"]["message"]


def _counts(db_session, a, b) -> dict:
    db_session.expire_all()
    return {
        "items": db_session.query(ContentItem)
        .filter(
            ContentItem.organisation_id.in_(
                [uuid.UUID(a.organisation_id), uuid.UUID(b.organisation_id)]
            )
        )
        .count(),
        "approvals": db_session.query(ApprovalEvent).count(),
        "sources": db_session.query(BrandSource)
        .filter(BrandSource.brand_profile_id.in_([uuid.UUID(a.brand_id), uuid.UUID(b.brand_id)]))
        .count(),
        "b_audit": db_session.query(AuditEvent)
        .filter_by(organisation_id=uuid.UUID(b.organisation_id))
        .count(),
    }


@requires_db
def test_b_cannot_list_or_read_a(client, force_stub_mode, account_factory) -> None:
    a, b = account_factory("a"), account_factory("b")
    review = a.submit()
    rnd = str(uuid.uuid4())

    _assert_same_404(
        client.get(f"/api/brands/{a.brand_id}/sources", headers=b.headers),
        client.get(f"/api/brands/{rnd}/sources", headers=b.headers),
    )
    _assert_same_404(
        client.get(f"/api/reviews/{review['id']}", headers=b.headers),
        client.get(f"/api/reviews/{rnd}", headers=b.headers),
    )
    _assert_same_404(
        client.get(f"/api/content/{review['content_item_id']}/history", headers=b.headers),
        client.get(f"/api/content/{rnd}/history", headers=b.headers),
    )
    b_brand_ids = {brand["id"] for brand in client.get("/api/brands", headers=b.headers).json()}
    assert b_brand_ids == {b.brand_id}
    assert a.brand_id not in b_brand_ids


@requires_db
def test_b_cannot_review_against_a_brand(
    client, force_stub_mode, db_session, account_factory
) -> None:
    a, b = account_factory("a"), account_factory("b")
    before = _counts(db_session, a, b)
    rnd = str(uuid.uuid4())

    _assert_same_404(
        client.post(
            "/api/reviews", json={"brand_id": a.brand_id, "text": "Probe."}, headers=b.headers
        ),
        client.post("/api/reviews", json={"brand_id": rnd, "text": "Probe."}, headers=b.headers),
    )
    _assert_same_404(
        client.post(
            "/api/reviews/upload",
            data={"brand_id": a.brand_id},
            files=_file("Probe."),
            headers=b.headers,
        ),
        client.post(
            "/api/reviews/upload", data={"brand_id": rnd}, files=_file("Probe."), headers=b.headers
        ),
    )
    assert _counts(db_session, a, b) == before  # nothing created in either account


@requires_db
def test_b_cannot_decide_or_edit_a_content(
    client, force_stub_mode, db_session, account_factory
) -> None:
    a, b = account_factory("a"), account_factory("b")
    review = a.submit()
    cv, item = review["content_version_id"], review["content_item_id"]
    rnd = str(uuid.uuid4())
    before = _counts(db_session, a, b)

    _assert_same_404(
        client.post(f"/api/content-versions/{cv}/approve", headers=b.headers),
        client.post(f"/api/content-versions/{rnd}/approve", headers=b.headers),
    )
    body = {"decision": "changes_requested", "note": "probe"}
    _assert_same_404(
        client.post(f"/api/content-versions/{cv}/request-changes", json=body, headers=b.headers),
        client.post(f"/api/content-versions/{rnd}/request-changes", json=body, headers=b.headers),
    )
    _assert_same_404(
        client.post(f"/api/reviews/{review['id']}/rerun", headers=b.headers),
        client.post(f"/api/reviews/{rnd}/rerun", headers=b.headers),
    )
    _assert_same_404(
        client.post(
            f"/api/content/{item}/versions", json={"text": "Overwrite."}, headers=b.headers
        ),
        client.post(f"/api/content/{rnd}/versions", json={"text": "Overwrite."}, headers=b.headers),
    )

    assert _counts(db_session, a, b) == before
    after = client.get(f"/api/reviews/{review['id']}", headers=a.headers).json()
    assert after["status"] == review["status"]  # A's review untouched
    history = client.get(f"/api/content/{item}/history", headers=a.headers).json()
    assert len(history["versions"]) == 1 and history["versions"][0]["decisions"] == []


@requires_db
def test_b_cannot_upload_or_change_a_sources(client, db_session, account_factory) -> None:
    a, b = account_factory("a"), account_factory("b")
    rnd = str(uuid.uuid4())
    before = _counts(db_session, a, b)

    _assert_same_404(
        client.post(
            f"/api/brands/{a.brand_id}/sources",
            data={"title": "x", "approve": "true"},
            files=_file(),
            headers=b.headers,
        ),
        client.post(
            f"/api/brands/{rnd}/sources",
            data={"title": "x", "approve": "true"},
            files=_file(),
            headers=b.headers,
        ),
    )
    _assert_same_404(
        client.post(f"/api/brands/{a.brand_id}/sources/{a.source_id}/approve", headers=b.headers),
        client.post(f"/api/brands/{rnd}/sources/{rnd}/approve", headers=b.headers),
    )
    withdraw = {"status": "archived", "reason": "probe"}
    _assert_same_404(
        client.post(
            f"/api/brands/{a.brand_id}/sources/{a.source_id}/withdraw",
            json=withdraw,
            headers=b.headers,
        ),
        client.post(f"/api/brands/{rnd}/sources/{rnd}/withdraw", json=withdraw, headers=b.headers),
    )
    _assert_same_404(
        client.post(
            f"/api/brands/{a.brand_id}/sources/{a.source_id}/versions",
            files=_file(),
            headers=b.headers,
        ),
        client.post(f"/api/brands/{rnd}/sources/{rnd}/versions", files=_file(), headers=b.headers),
    )
    # B's own brand id with A's source id: the source must not resolve through a brand B owns.
    _assert_same_404(
        client.post(
            f"/api/brands/{b.brand_id}/sources/{a.source_id}/withdraw",
            json=withdraw,
            headers=b.headers,
        ),
        client.post(
            f"/api/brands/{b.brand_id}/sources/{rnd}/withdraw", json=withdraw, headers=b.headers
        ),
    )

    assert _counts(db_session, a, b) == before
    [a_source] = client.get(f"/api/brands/{a.brand_id}/sources", headers=a.headers).json()
    assert a_source["status"] == "approved" and a_source["latest_version"] == 1
