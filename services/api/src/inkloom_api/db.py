"""SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def build_engine(database_url: str, statement_timeout_ms: int):
    connect_args = {}
    if database_url.startswith("postgresql"):
        # Server-side cap on every statement, so a slow query cannot hold a worker forever. Any
        # `options` already in DATABASE_URL (e.g. `?options=-csearch_path%3Dinkloom_test`, the
        # throwaway test schema in README "Test") are kept: connect_args would otherwise replace
        # them.
        url_options = make_url(database_url).query.get("options")
        options = [url_options] if isinstance(url_options, str) and url_options else []
        options.append(f"-c statement_timeout={int(statement_timeout_ms)}")
        connect_args["options"] = " ".join(options)
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = build_engine(settings.database_url, settings.db_statement_timeout_ms)
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
