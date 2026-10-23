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


requires_db = pytest.mark.skipif(not _database_reachable(), reason="DATABASE_URL not set or not reachable")


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
    "GEMINI_API_KEY", "GEMINI_MODEL",
    "GROQ_API_KEY", "GROQ_MODEL",
    "OPENROUTER_API_KEY", "INKLOOM_LLM_MODELS",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL",
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
