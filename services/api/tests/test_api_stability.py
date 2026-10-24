"""Phase 2 (contracts and stability): inputs that used to crash the API with a 500, or answer
outside the standard error shape, now fail safely and predictably.

1. every error - including the router's own 404/405 and an unhandled exception - is the standard
   `{"error": {code, message, request_id}}` body, and every response carries X-Request-ID; only
   login, register and /health are open, and every other route answers 401 without a token;
2. a caller's X-Request-ID is reused only if it looks like an id;
3. a NUL (0x00) character, which PostgreSQL text can't store, is a 422 on every free-text field
   and in uploaded files, and nothing is stored;
4. an Idempotency-Key the database can't hold is a 422 before any work;
5. two requests with the same Idempotency-Key at once produce one review, not a duplicate and a
   500; one still running past the statement timeout gets a 409; a failed request frees its key.
"""

from __future__ import annotations

import io
import re
import threading
import time
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import requires_db
from inkloom_api.models import ContentItem, IdempotencyKey

REVIEW_TEXT = "Lumen Pods offer up to 12 hours of playback per charge."


@pytest.fixture
def safe_client():
    """Answers an unhandled exception with the app's own 500, as a real server does."""
    from inkloom_api.main import app

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def _assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    assert body["error"]["request_id"] == response.headers["X-Request-ID"] != "-"
    return body["error"]


def _content_items(db_session, account) -> int:
    db_session.expire_all()
    return db_session.query(ContentItem).filter_by(organisation_id=uuid.UUID(account.organisation_id)).count()


# 1-2. Error shape and request ids --------------------------------------------------------------


def test_unknown_route_and_wrong_method_use_the_error_shape(client) -> None:
    _assert_error(client.get("/api/no-such-route"), 404, "NOT_FOUND")
    _assert_error(client.delete("/health"), 405, "NOT_FOUND")


@requires_db
def test_unhandled_exception_is_a_safe_500_with_the_request_id(safe_client, account_factory, monkeypatch) -> None:
    from inkloom_api.routers import reviews

    owner = account_factory("owner", with_source=False)

    def boom(*args, **kwargs):
        raise RuntimeError("postgresql://inkloom:hunter2@db/inkloom")

    monkeypatch.setattr(reviews, "get_review_or_404", boom)
    response = safe_client.get(f"/api/reviews/{uuid.uuid4()}", headers={**owner.headers, "X-Request-ID": "trace-500"})
    error = _assert_error(response, 500, "INTERNAL_ERROR")
    assert error == {"code": "INTERNAL_ERROR", "message": "an internal error occurred", "request_id": "trace-500"}
    assert "hunter2" not in response.text


@pytest.mark.parametrize(
    ("incoming", "reused"),
    [("abc-123_X.y", True), ("r" * 128, True), ("r" * 129, False), ("<script>alert(1)</script>", False), ("a b", False)],
)
def test_caller_request_id_is_reused_only_if_it_looks_like_an_id(client, incoming, reused) -> None:
    response = client.get("/api/no-such-route", headers={"X-Request-ID": incoming})
    assert (response.headers["X-Request-ID"] == incoming) is reused
    if not reused:
        assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]


OPEN_OPERATIONS = {("POST", "/api/auth/login"), ("POST", "/api/auth/register"), ("GET", "/health")}


def _operations():
    from inkloom_api.main import app

    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            yield method.upper(), path, operation


def test_only_login_register_and_health_are_open_and_every_route_has_a_response_schema() -> None:
    """A new route without the auth dependency (or without a response model) fails here."""
    operations = list(_operations())
    assert {(m, p) for m, p, op in operations if not op.get("security")} == OPEN_OPERATIONS
    for method, path, operation in operations:
        success = next(code for code in operation["responses"] if code.startswith("2"))
        assert operation["responses"][success]["content"]["application/json"]["schema"], (method, path)


def test_every_protected_route_refuses_a_request_without_a_token(client) -> None:
    for method, path, operation in _operations():
        if (method, path) in OPEN_OPERATIONS:
            continue
        url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
        error = _assert_error(client.request(method, url), 401, "UNAUTHENTICATED")
        assert error["message"] == "authentication required", (method, path)


# 3. NUL characters ------------------------------------------------------------------------------


@requires_db
def test_nul_in_any_free_text_field_is_a_422_and_nothing_is_stored(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    before = _content_items(db_session, owner)
    nul = "a\x00b"
    source_url = f"/api/brands/{owner.brand_id}/sources"
    cases = [
        ("POST", "/api/reviews", {"json": {"brand_id": owner.brand_id, "text": f"Lumen {nul} Pods"}}, "body.text"),
        ("POST", "/api/reviews", {"json": {"brand_id": owner.brand_id, "title": nul, "text": REVIEW_TEXT}}, "body.title"),
        ("POST", "/api/brands", {"json": {"name": nul}}, "body.name"),
        ("POST", "/api/brands", {"json": {"name": "Ok", "description": nul}}, "body.description"),
        ("POST", f"/api/content/{review['content_item_id']}/versions", {"json": {"text": nul}}, "body.text"),
        ("POST", f"/api/content-versions/{review['content_version_id']}/request-changes",
         {"json": {"decision": "changes_requested", "note": nul}}, "body.note"),
        ("POST", f"{source_url}/{owner.source_id}/withdraw", {"json": {"status": "archived", "reason": nul}}, "body.reason"),
        ("POST", source_url, {"data": {"title": nul}, "files": {"file": ("a.txt", b"Fact.", "text/plain")}}, "body.title"),
        ("POST", "/api/reviews/upload", {"data": {"brand_id": owner.brand_id, "title": nul},
                                          "files": {"file": ("a.txt", b"Draft.", "text/plain")}}, "body.title"),
    ]
    for method, url, kwargs, field in cases:
        error = _assert_error(client.request(method, url, headers=owner.headers, **kwargs), 422, "VALIDATION_ERROR")
        assert field in error["message"] and "\x00" not in error["message"], (url, error)

    for field in ("display_name", "organisation_name", "brand_name"):
        body = {"email": f"nul-{uuid.uuid4().hex[:8]}@example.com", "password": "correct-horse-1", field: nul}
        error = _assert_error(client.post("/api/auth/register", json=body), 422, "VALIDATION_ERROR")
        assert f"body.{field}" in error["message"]

    assert _content_items(db_session, owner) == before
    sources = client.get(source_url, headers=owner.headers).json()
    assert [s["status"] for s in sources] == ["approved"]  # not withdrawn, nothing added


@requires_db
def test_uploaded_file_with_nul_characters_is_a_422(client, force_stub_mode, db_session, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    utf16_without_bom = "Lumen Pods: 12 hours.".encode("utf-16-le")  # valid UTF-8, full of NULs
    for url, data in ((f"/api/brands/{owner.brand_id}/sources", {"title": "Facts"}),
                      ("/api/reviews/upload", {"brand_id": owner.brand_id})):
        response = client.post(url, data=data, files={"file": ("facts.txt", io.BytesIO(utf16_without_bom), "text/plain")},
                               headers=owner.headers)
        error = _assert_error(response, 422, "VALIDATION_ERROR")
        assert "NUL" in error["message"]
    assert client.get(f"/api/brands/{owner.brand_id}/sources", headers=owner.headers).json() == []
    assert _content_items(db_session, owner) == 0


# 4-5. Idempotency keys --------------------------------------------------------------------------


@requires_db
@pytest.mark.parametrize("key", ["k" * 201, "has space", ""])
def test_unusable_idempotency_key_is_a_422_before_any_work(client, force_stub_mode, db_session, account_factory, key) -> None:
    owner = account_factory("owner")
    review = owner.submit()
    before = _content_items(db_session, owner)
    headers = {**owner.headers, "Idempotency-Key": key}
    for response in (
        client.post("/api/reviews", json={"brand_id": owner.brand_id, "text": REVIEW_TEXT}, headers=headers),
        client.post(f"/api/reviews/{review['id']}/rerun", headers=headers),
    ):
        _assert_error(response, 422, "VALIDATION_ERROR")
    assert _content_items(db_session, owner) == before
    assert len(client.get("/api/reviews", headers=owner.headers).json()) == 1


@requires_db
def test_a_200_character_idempotency_key_still_works(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner")
    headers = {**owner.headers, "Idempotency-Key": "k" * 200}
    body = {"brand_id": owner.brand_id, "text": REVIEW_TEXT}
    first = client.post("/api/reviews", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert client.post("/api/reviews", json=body, headers=headers).json()["id"] == first.json()["id"]


@requires_db
def test_concurrent_requests_with_one_key_make_one_review(client, force_stub_mode, db_session, account_factory, monkeypatch) -> None:
    """A double click: both requests are in flight together. The second waits for the first and
    replays its response; it neither runs a second review nor fails on the key's unique index."""
    from inkloom_api.routers import reviews

    owner = account_factory("owner")
    real_start_review = reviews.start_review

    def slow_start_review(*args, **kwargs):
        time.sleep(1.0)  # keeps the first request's transaction open while the second arrives
        return real_start_review(*args, **kwargs)

    monkeypatch.setattr(reviews, "start_review", slow_start_review)
    headers = {**owner.headers, "Idempotency-Key": "double-click"}
    body = {"brand_id": owner.brand_id, "text": REVIEW_TEXT}
    responses: list = []
    threads = [threading.Thread(target=lambda: responses.append(client.post("/api/reviews", json=body, headers=headers)))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert responses[0].json()["id"] == responses[1].json()["id"]
    assert _content_items(db_session, owner) == 1
    assert len(client.get("/api/reviews", headers=owner.headers).json()) == 1


@requires_db
def test_key_held_by_a_request_still_running_is_a_409(db_session, account_factory) -> None:
    """Request A holds the key (uncommitted); request B times out waiting for it -> 409. Once A
    rolls back (it failed), the key is free again."""
    from inkloom_api.db import get_session_factory
    from inkloom_api.idempotency import claim

    owner = account_factory("owner", with_source=False)
    org = uuid.UUID(owner.organisation_id)
    first, second = get_session_factory()(), get_session_factory()()
    try:
        assert claim(first, org, "POST /api/reviews", "held", "hash") is None  # A: reserved, not committed
        second.execute(text("SET statement_timeout = 300"))
        with pytest.raises(HTTPException) as caught:
            claim(second, org, "POST /api/reviews", "held", "hash")
        assert caught.value.status_code == 409 and "still being processed" in caught.value.detail

        first.rollback()  # A failed
        second.rollback()
        assert claim(second, org, "POST /api/reviews", "held", "hash") is None  # B may run now
    finally:
        first.close()
        second.rollback()
        second.close()


@requires_db
def test_a_failed_request_frees_its_key_for_a_retry(safe_client, force_stub_mode, db_session, account_factory, monkeypatch) -> None:
    from inkloom_api.routers import reviews

    owner = account_factory("owner")
    real_start_review = reviews.start_review
    calls = {"n": 0}

    def fail_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("engine crashed")
        return real_start_review(*args, **kwargs)

    monkeypatch.setattr(reviews, "start_review", fail_once)
    headers = {**owner.headers, "Idempotency-Key": "retry-me"}
    body = {"brand_id": owner.brand_id, "text": REVIEW_TEXT}
    _assert_error(safe_client.post("/api/reviews", json=body, headers=headers), 500, "INTERNAL_ERROR")
    db_session.expire_all()
    assert db_session.query(IdempotencyKey).filter_by(key="retry-me").count() == 0
    assert _content_items(db_session, owner) == 0

    retry = safe_client.post("/api/reviews", json=body, headers=headers)
    assert retry.status_code == 201, retry.text
    assert safe_client.post("/api/reviews", json=body, headers=headers).json()["id"] == retry.json()["id"]
