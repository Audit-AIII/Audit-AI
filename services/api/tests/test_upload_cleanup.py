"""A source upload whose database commit fails leaves no file behind.

Both upload routes write the raw file to disk (`store_upload`) before committing. If the commit
(or anything before it) raises, the stored file is deleted and the original error still
propagates unchanged - to the app's catch-all handler, which answers 500 and logs its type:

1. A new source.                       -> POST /api/brands/{id}/sources
2. A new version of an existing source. -> POST /api/brands/{id}/sources/{source_id}/versions
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from conftest import requires_db
from inkloom_api.config import get_settings
from inkloom_api.routers import brands

pytestmark = requires_db


class CommitFailed(Exception):
    pass


@pytest.mark.parametrize("route", ["new_source", "new_version"])
def test_failed_commit_removes_the_stored_file(
    client, monkeypatch, caplog, account_factory, route
) -> None:
    owner = account_factory("owner")
    url = f"/api/brands/{owner.brand_id}/sources"
    data = {"title": "Fact sheet"}
    if route == "new_version":
        url = f"{url}/{owner.source_id}/versions"
        data = {}

    stored = []
    real_store_upload = brands.store_upload

    def recording_store_upload(*args, **kwargs):
        path = real_store_upload(*args, **kwargs)
        stored.append(Path(get_settings().brand_source_storage_dir) / path)
        assert stored[-1].exists()  # the file really was written before the commit
        return path

    def failing_commit(self):
        raise CommitFailed("database went away")

    caplog.set_level(logging.ERROR, logger="inkloom_api.errors")
    with monkeypatch.context() as patched:  # undone before the fixtures clean up (they commit)
        patched.setattr(brands, "store_upload", recording_store_upload)
        patched.setattr(Session, "commit", failing_commit)
        response = client.post(
            url,
            data=data,
            files={"file": ("facts.txt", io.BytesIO(b"The lid is bamboo."), "text/plain")},
            headers=owner.headers,
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    unhandled = [r.getMessage() for r in caplog.records if r.name == "inkloom_api.errors"]
    assert len(unhandled) == 1
    assert unhandled[0].startswith("unhandled exception CommitFailed\n")
    assert len(stored) == 1
    assert not stored[0].exists()
