"""Shared test fixtures.

Requires a reachable Postgres (see ../docker-compose.yml) at DATABASE_URL, and migrations
applied (`alembic upgrade head`). Tests that need the database are skipped otherwise, rather
than silently passing against a mock: this phase's job is to prove the real schema and the real
auth dependency work.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine


def _database_reachable() -> bool:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False
    try:
        create_engine(url).connect().close()
        return True
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _database_reachable(), reason="DATABASE_URL not set or not reachable"
)


@pytest.fixture
def db_engine():
    from inkloom_api.db import get_engine

    return get_engine()


@pytest.fixture
def db_session():
    from inkloom_api.db import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from inkloom_api.main import app

    with TestClient(app) as test_client:
        yield test_client


# Every env var any of the four fallback-chain providers (Phase 5) treats as "configured".
# Deleting all of them is the only way to force stub mode in a test - deleting just OpenRouter's
# pair leaves Gemini/Groq/Ollama able to pick up real credentials from the developer's own
# .env and make a real network call during what's supposed to be an isolated test.
_PROVIDER_ENV_VARS = (
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "OPENROUTER_API_KEY",
    "INKLOOM_LLM_MODELS",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
)


@pytest.fixture
def force_stub_mode(monkeypatch):
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Phase 5 task 7's rate limiter is in-memory, global, fixed-window state - without this,
    the many tests that call POST /api/reviews would share counters and flake once enough of
    them land inside the same window, unrelated to what any individual test is checking."""
    from inkloom_api.rate_limit import reset_rate_limits

    reset_rate_limits()
    yield
    reset_rate_limits()


# ---------------------------------------------------------------------------------------------
# Individual-user accounts (product decision 2026-10-24: one email = one private account).
# ---------------------------------------------------------------------------------------------

ACCOUNT_PASSWORD = "correct-horse-battery-staple"
DEFAULT_FACT_SHEET = (
    "Lumen Pods - Product Fact Sheet\n\n"
    "Battery life: up to 12 hours of playback per charge; up to 36 hours with the charging case.\n"
    "Water resistance: IPX4 (splash resistant). Not suitable for swimming.\n"
    "Warranty: 2 years.\n"
)


class Account:
    """One registered individual account, created through the real HTTP routes."""

    def __init__(self, client, body: dict) -> None:
        self.client = client
        self.token: str = body["access_token"]
        self.user_id: str = body["user"]["id"]
        self.organisation_id: str = body["organisation"]["id"]
        self.brand_id: str = body["brand"]["id"]
        self.role: str = body["role"]
        self.source_id: str | None = None

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def upload_source(
        self, text: str = DEFAULT_FACT_SHEET, brand_id: str | None = None, title: str = "Fact Sheet"
    ) -> dict:
        import io

        response = self.client.post(
            f"/api/brands/{brand_id or self.brand_id}/sources",
            data={"title": title, "approve": "true"},
            files={"file": ("facts.txt", io.BytesIO(text.encode("utf-8")), "text/plain")},
            headers=self.headers,
        )
        assert response.status_code == 201, response.text
        if brand_id is None:
            self.source_id = response.json()["id"]
        return response.json()

    def submit(
        self,
        text: str = "Lumen Pods offer up to 12 hours of playback per charge.",
        brand_id: str | None = None,
        title: str | None = None,
    ) -> dict:
        body = {"brand_id": brand_id or self.brand_id, "text": text}
        if title is not None:
            body["title"] = title
        response = self.client.post("/api/reviews", json=body, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()

    def create_brand(self, name: str) -> dict:
        response = self.client.post("/api/brands", json={"name": name}, headers=self.headers)
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def account_factory(client, db_session):
    """`account_factory(label, with_source=True)` registers a brand-new private account (its own
    organisation, `admin` membership = account owner, starter brand), optionally uploads one
    approved fact sheet, and deletes everything it created afterwards."""
    import uuid as _uuid

    from inkloom_api.models import Organisation, User

    created: list[Account] = []

    def make(label: str = "user", with_source: bool = True) -> Account:
        email = f"{label}-{_uuid.uuid4().hex[:10]}@example.com"
        response = client.post(
            "/api/auth/register", json={"email": email, "password": ACCOUNT_PASSWORD}
        )
        assert response.status_code == 201, response.text
        account = Account(client, response.json())
        created.append(account)
        if with_source:
            account.upload_source()
        return account

    yield make

    from sqlalchemy import text as _text

    db_session.rollback()
    for account in created:
        # Content first: deleting the organisation in one go makes Postgres run brand_sources'
        # ON DELETE SET NULL on evidence_links rows the same cascade already removed via findings.
        db_session.execute(
            _text("DELETE FROM content_items WHERE organisation_id = :id"),
            {"id": account.organisation_id},
        )
        org = db_session.get(Organisation, _uuid.UUID(account.organisation_id))
        if org is not None:
            db_session.delete(org)
        db_session.flush()
        user = db_session.get(User, _uuid.UUID(account.user_id))
        if user is not None:
            db_session.delete(user)
    db_session.commit()


def use_scripted_provider(monkeypatch, rules) -> None:
    """Routes every review in this test through the offline scripted provider
    (inkloom_api.engine.scripted_provider) - real engine code, deterministic verdicts, no network."""
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider
    from inkloom_api.engine.scripted_provider import scripted_provider

    def build(confidential=False, on_attempt=None):
        return FallbackProvider(
            [("scripted", lambda: scripted_provider(rules))],
            on_attempt=on_attempt or (lambda **_: None),
        )

    monkeypatch.setattr(pipeline, "build_provider", build)
