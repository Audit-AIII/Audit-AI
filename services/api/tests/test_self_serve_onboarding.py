"""Self-serve onboarding (docs/backend.md, "Self-serve onboarding"): a visitor signs up
with any email, gets a private organisation + `admin` membership + a starter brand in one
transaction, uploads one PDF (approved in the same step), then checks a draft against it - no
brand id ever needed by hand.

Covers:
1. register creates admin + workspace + brand; token works on GET /api/auth/me.
   -> test_register_creates_admin_workspace_and_brand
2. defaults with only email + password.
   -> test_register_defaults_with_only_email_and_password
3. body cannot choose role or organisation.
   -> test_register_body_cannot_choose_role_or_organisation
4. duplicate email -> 409, case-insensitively.
   -> test_register_duplicate_email_rejected_case_insensitively
5. weak passwords -> 422 (too short, blank, "é"*40 = 80 bytes).
   -> test_register_rejects_weak_passwords
6. login is case-insensitive and returns expires_in.
   -> test_login_case_insensitive_with_expires_in
7. registration is rate-limited per IP.
   -> test_register_rate_limited_per_ip
8. two sign-ups can't see each other's brands.
   -> test_two_signups_cannot_see_each_others_brands
9. create brand, duplicate name -> 409, list order (sign-up brand first).
   -> test_create_brand_duplicate_and_list_order
10. GET /api/brands with no token -> 401.
    -> test_list_brands_requires_auth
11. approve=true on brand-source upload -> approved + both audit events; default stays draft.
    -> test_brand_source_approve_on_upload
12. full flow: approve-upload a .txt fact sheet, then a .docx draft via /api/reviews/upload.
    -> test_full_self_serve_flow_with_docx_draft
13. an unsupported file extension (.exe) -> 422.
    -> test_upload_rejects_exe_file
14. draft upload to another tenant's brand -> 404, and no ContentItem is created.
    -> test_upload_to_another_tenants_brand_is_404_and_creates_nothing
15. same Idempotency-Key replays the same review; a different key creates a new one.
    -> test_upload_idempotency_key_replays_same_review

All forced into stub mode (force_stub_mode) - this tests the onboarding/tenancy/audit machinery,
not the AI engine.
"""

from __future__ import annotations

import io
import uuid

import docx
import pytest

from conftest import requires_db
from inkloom_api.config import get_settings
from inkloom_api.models import AuditEvent, ContentItem, Membership, Organisation, User

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def cleanup(db_session):
    """Each call to POST /api/auth/register creates a brand-new Organisation + User - that's the
    point of self-serve onboarding. Tests append the (organisation_id, user_id) pair they created
    here; deleting the organisation cascades its memberships/brand/content/audit events, and the
    user (not owned by any organisation) is deleted separately, same pattern as
    test_source_lifecycle.py's fixture."""
    created: list[tuple[uuid.UUID, uuid.UUID]] = []
    yield created
    for org_id, user_id in created:
        org = db_session.get(Organisation, org_id)
        if org is not None:
            db_session.delete(org)
        user = db_session.get(User, user_id)
        if user is not None:
            db_session.delete(user)
    db_session.commit()


def _unique_email(label: str) -> str:
    return f"{label}-{uuid.uuid4().hex[:10]}@example.com"


def _register(client, email: str, password: str = PASSWORD, **extra) -> dict:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": password, **extra}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_docx_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    document = docx.Document()
    document.add_paragraph(text)
    document.save(buffer)
    return buffer.getvalue()


@requires_db
def test_register_creates_admin_workspace_and_brand(client, force_stub_mode, cleanup) -> None:
    email = _unique_email("register-basic")
    body = _register(
        client,
        email,
        display_name="Ada Lovelace",
        organisation_name="Ada Co",
        brand_name="Ada Brand",
    )
    cleanup.append((uuid.UUID(body["organisation"]["id"]), uuid.UUID(body["user"]["id"])))

    assert body["role"] == "admin"
    assert body["user"]["email"] == email.lower()
    assert body["organisation"]["name"] == "Ada Co"
    assert body["brand"]["name"] == "Ada Brand"
    assert body["brand"]["approved_source_count"] == 0
    assert body["expires_in"] == get_settings().auth_token_ttl_minutes * 60

    me = client.get("/api/auth/me", headers=_auth(body["access_token"]))
    assert me.status_code == 200, me.text
    assert me.json()["role"] == "admin"
    assert me.json()["organisation"]["id"] == body["organisation"]["id"]


@requires_db
def test_register_defaults_with_only_email_and_password(client, force_stub_mode, cleanup) -> None:
    email = _unique_email("register-defaults")
    body = _register(client, email)
    cleanup.append((uuid.UUID(body["organisation"]["id"]), uuid.UUID(body["user"]["id"])))

    local_part = email.split("@", 1)[0]
    assert body["organisation"]["name"] == f"{local_part}'s workspace"
    assert body["brand"]["name"] == "My brand"
    assert body["user"]["display_name"] is None


@requires_db
def test_register_body_cannot_choose_role_or_organisation(
    client, force_stub_mode, cleanup, db_session
) -> None:
    """Extra fields in the body (role, organisation_id) are silently ignored - the role is always
    `admin` and the organisation is always the one created in this same transaction."""
    email = _unique_email("register-escalate")
    bogus_org_id = str(uuid.uuid4())
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "role": "submitter",
            "organisation_id": bogus_org_id,
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    cleanup.append((uuid.UUID(body["organisation"]["id"]), uuid.UUID(body["user"]["id"])))

    assert body["role"] == "admin"
    assert body["organisation"]["id"] != bogus_org_id
    membership = db_session.query(Membership).filter_by(user_id=uuid.UUID(body["user"]["id"])).one()
    assert membership.role == "admin"


@requires_db
def test_register_duplicate_email_rejected_case_insensitively(
    client, force_stub_mode, cleanup
) -> None:
    email = _unique_email("dup")
    first = _register(client, email)
    cleanup.append((uuid.UUID(first["organisation"]["id"]), uuid.UUID(first["user"]["id"])))

    response = client.post(
        "/api/auth/register", json={"email": email.upper(), "password": PASSWORD}
    )
    assert response.status_code == 409, response.text
    assert "already exists" in response.json()["error"]["message"]


@requires_db
@pytest.mark.parametrize(
    "password", ["short1", "", "é" * 40], ids=["too_short", "blank", "eighty_bytes"]
)
def test_register_rejects_weak_passwords(client, force_stub_mode, password: str) -> None:
    response = client.post(
        "/api/auth/register", json={"email": _unique_email("weakpw"), "password": password}
    )
    assert response.status_code == 422, response.text


@requires_db
def test_login_case_insensitive_with_expires_in(client, force_stub_mode, cleanup) -> None:
    email = _unique_email("login-ci")
    registered = _register(client, email)
    cleanup.append(
        (uuid.UUID(registered["organisation"]["id"]), uuid.UUID(registered["user"]["id"]))
    )

    response = client.post("/api/auth/login", json={"email": email.upper(), "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["expires_in"] == get_settings().auth_token_ttl_minutes * 60


@requires_db
def test_register_rate_limited_per_ip(client, force_stub_mode, monkeypatch, cleanup) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_registrations_per_ip", 2)

    for _ in range(2):
        body = _register(client, _unique_email("ratelimit"))
        cleanup.append((uuid.UUID(body["organisation"]["id"]), uuid.UUID(body["user"]["id"])))

    response = client.post(
        "/api/auth/register", json={"email": _unique_email("ratelimit"), "password": PASSWORD}
    )
    assert response.status_code == 429, response.text


@requires_db
def test_two_signups_cannot_see_each_others_brands(client, force_stub_mode, cleanup) -> None:
    a = _register(client, _unique_email("tenant-a"))
    b = _register(client, _unique_email("tenant-b"))
    cleanup.append((uuid.UUID(a["organisation"]["id"]), uuid.UUID(a["user"]["id"])))
    cleanup.append((uuid.UUID(b["organisation"]["id"]), uuid.UUID(b["user"]["id"])))

    cross_tenant = client.get(
        f"/api/brands/{a['brand']['id']}/sources", headers=_auth(b["access_token"])
    )
    assert cross_tenant.status_code == 404, cross_tenant.text

    own_brands = client.get("/api/brands", headers=_auth(a["access_token"]))
    assert [brand["id"] for brand in own_brands.json()] == [a["brand"]["id"]]


@requires_db
def test_create_brand_duplicate_and_list_order(client, force_stub_mode, cleanup) -> None:
    user = _register(client, _unique_email("brandlist"))
    cleanup.append((uuid.UUID(user["organisation"]["id"]), uuid.UUID(user["user"]["id"])))
    token = user["access_token"]

    created = client.post(
        "/api/brands", json={"name": "Second Brand", "description": "desc"}, headers=_auth(token)
    )
    assert created.status_code == 201, created.text
    assert created.json()["name"] == "Second Brand"
    assert created.json()["approved_source_count"] == 0

    duplicate = client.post("/api/brands", json={"name": "Second Brand"}, headers=_auth(token))
    assert duplicate.status_code == 409, duplicate.text

    listed = client.get("/api/brands", headers=_auth(token))
    assert [brand["name"] for brand in listed.json()] == ["My brand", "Second Brand"]


def test_list_brands_requires_auth(client) -> None:
    response = client.get("/api/brands")
    assert response.status_code == 401


@requires_db
def test_brand_source_approve_on_upload(client, force_stub_mode, cleanup, db_session) -> None:
    user = _register(client, _unique_email("approve-upload"))
    cleanup.append((uuid.UUID(user["organisation"]["id"]), uuid.UUID(user["user"]["id"])))
    token, brand_id = user["access_token"], user["brand"]["id"]

    approved = client.post(
        f"/api/brands/{brand_id}/sources",
        headers=_auth(token),
        data={"title": "Fact Sheet", "approve": "true"},
        files={"file": ("facts.txt", io.BytesIO(b"Fact: the sky is blue."), "text/plain")},
    )
    assert approved.status_code == 201, approved.text
    assert approved.json()["status"] == "approved"

    events = (
        db_session.query(AuditEvent)
        .filter_by(
            organisation_id=uuid.UUID(user["organisation"]["id"]), entity_id=approved.json()["id"]
        )
        .all()
    )
    assert {e.event_type for e in events} == {"brand_source.uploaded", "brand_source.approved"}
    approved_event = next(e for e in events if e.event_type == "brand_source.approved")
    assert approved_event.details == {"previous_status": "draft", "approved_on_upload": True}

    default_draft = client.post(
        f"/api/brands/{brand_id}/sources",
        headers=_auth(token),
        data={"title": "Another"},
        files={"file": ("facts2.txt", io.BytesIO(b"Fact: grass is green."), "text/plain")},
    )
    assert default_draft.status_code == 201, default_draft.text
    assert default_draft.json()["status"] == "draft"


@requires_db
def test_full_self_serve_flow_with_docx_draft(client, force_stub_mode, cleanup) -> None:
    user = _register(client, _unique_email("full-flow"))
    cleanup.append((uuid.UUID(user["organisation"]["id"]), uuid.UUID(user["user"]["id"])))
    token, brand_id = user["access_token"], user["brand"]["id"]

    source = client.post(
        f"/api/brands/{brand_id}/sources",
        headers=_auth(token),
        data={"title": "Fact Sheet", "approve": "true"},
        files={
            "file": (
                "facts.txt",
                io.BytesIO(b"Fact: the Lumen Widget weighs 200 grams."),
                "text/plain",
            )
        },
    )
    assert source.status_code == 201, source.text
    assert source.json()["status"] == "approved"

    draft_bytes = _make_docx_bytes("Draft: the Lumen Widget weighs 150 grams.")
    uploaded = client.post(
        "/api/reviews/upload",
        headers=_auth(token),
        data={"brand_id": brand_id},
        files={
            "file": (
                "my-draft.docx",
                draft_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["status"] in ("completed", "needs_human_review")
    assert body["brand_id"] == brand_id
    assert body["version_number"] == 1
    assert body["title"] == "my-draft"  # defaulted to the filename stem - no title was given
    assert "Lumen Widget weighs 150 grams" in body["text"]
    content_item_id = body["content_item_id"]
    assert content_item_id is not None

    fetched = client.get(f"/api/reviews/{body['id']}", headers=_auth(token))
    assert fetched.status_code == 200, fetched.text
    for key in ("id", "brand_id", "content_item_id", "title", "version_number", "text", "status"):
        assert fetched.json()[key] == body[key]

    history = client.get(f"/api/content/{content_item_id}/history", headers=_auth(token))
    assert history.status_code == 200, history.text
    assert history.json()["title"] == "my-draft"
    assert history.json()["versions"][0]["reviews"][0]["id"] == body["id"]


@requires_db
def test_upload_rejects_exe_file(client, force_stub_mode, cleanup) -> None:
    user = _register(client, _unique_email("exe-reject"))
    cleanup.append((uuid.UUID(user["organisation"]["id"]), uuid.UUID(user["user"]["id"])))

    response = client.post(
        "/api/reviews/upload",
        headers=_auth(user["access_token"]),
        data={"brand_id": user["brand"]["id"]},
        files={"file": ("virus.exe", io.BytesIO(b"MZ\x00\x00fake"), "application/octet-stream")},
    )
    assert response.status_code == 422, response.text


@requires_db
def test_upload_to_another_tenants_brand_is_404_and_creates_nothing(
    client, force_stub_mode, cleanup, db_session
) -> None:
    owner = _register(client, _unique_email("cross-owner"))
    intruder = _register(client, _unique_email("cross-intruder"))
    cleanup.append((uuid.UUID(owner["organisation"]["id"]), uuid.UUID(owner["user"]["id"])))
    cleanup.append((uuid.UUID(intruder["organisation"]["id"]), uuid.UUID(intruder["user"]["id"])))

    intruder_org_id = uuid.UUID(intruder["organisation"]["id"])
    before = db_session.query(ContentItem).filter_by(organisation_id=intruder_org_id).count()

    response = client.post(
        "/api/reviews/upload",
        headers=_auth(intruder["access_token"]),
        data={"brand_id": owner["brand"]["id"]},
        files={"file": ("draft.txt", io.BytesIO(b"Some draft text."), "text/plain")},
    )
    assert response.status_code == 404, response.text

    after = db_session.query(ContentItem).filter_by(organisation_id=intruder_org_id).count()
    assert after == before == 0


@requires_db
def test_upload_idempotency_key_replays_same_review(client, force_stub_mode, cleanup) -> None:
    user = _register(client, _unique_email("idem"))
    cleanup.append((uuid.UUID(user["organisation"]["id"]), uuid.UUID(user["user"]["id"])))
    token, brand_id = user["access_token"], user["brand"]["id"]

    def _upload(key: str):
        return client.post(
            "/api/reviews/upload",
            headers={**_auth(token), "Idempotency-Key": key},
            data={"brand_id": brand_id},
            files={"file": ("draft.txt", io.BytesIO(b"Idempotent draft text."), "text/plain")},
        )

    first = _upload("same-key")
    assert first.status_code == 201, first.text
    replay = _upload("same-key")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == first.json()["id"]

    new_key = _upload("different-key")
    assert new_key.status_code == 201, new_key.text
    assert new_key.json()["id"] != first.json()["id"]
