"""`options` in DATABASE_URL are kept alongside the backend's own statement timeout (db.py).

Before, connect_args replaced them, so e.g. `?options=-csearch_path%3Dinkloom_test` (the throwaway
test schema, README "Test") was silently ignored and the tests ran against the dev tables.
"""

from __future__ import annotations

import os

from sqlalchemy import text
from sqlalchemy.engine import make_url

from conftest import requires_db
from inkloom_api.db import build_engine


@requires_db
def test_url_options_are_kept_with_the_statement_timeout() -> None:
    url = make_url(os.environ["DATABASE_URL"])
    existing = url.query.get("options")
    extra = "-c application_name=inkloom-options-test"
    url = url.update_query_dict({"options": f"{existing} {extra}" if existing else extra})
    engine = build_engine(url.render_as_string(hide_password=False), statement_timeout_ms=4321)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SHOW application_name")).scalar() == "inkloom-options-test"
            assert connection.execute(text("SHOW statement_timeout")).scalar() == "4321ms"
    finally:
        engine.dispose()
