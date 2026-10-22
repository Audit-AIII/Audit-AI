"""Proves migrations run up and down cleanly (Phase 1 "Done when")."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

from conftest import requires_db

SERVICE_ROOT = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(SERVICE_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "migrations"))
    return cfg


@requires_db
def test_upgrade_head_then_downgrade_base() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # leave the schema in place for other tests
