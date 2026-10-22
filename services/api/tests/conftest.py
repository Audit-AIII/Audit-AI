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
