from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import requires_db


@requires_db
def test_health_returns_ok_and_request_id() -> None:
    from inkloom_api.main import app  # imported lazily: constructing it needs DATABASE_URL

    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"]


@requires_db
def test_health_reuses_supplied_request_id() -> None:
    from inkloom_api.main import app

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "test-request-id"})
    assert response.headers["X-Request-ID"] == "test-request-id"
