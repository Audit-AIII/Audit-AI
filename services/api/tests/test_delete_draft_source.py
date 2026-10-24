"""DELETE /api/brands/{id}/sources/{source_id}: only a never-approved (draft) source can be deleted.

1. A draft is deleted (200 {"id", "title", "deleted": true}): gone from the list, its versions and
   its uploaded file removed, audited as brand_source.deleted with the title only (never the text).
2. An approved source is refused (409, "withdraw ... instead") and stays.
3. A withdrawn (archived) source is refused too: it is part of the record.
4. Another account's source is a 404, like a random id.
"""

from __future__ import annotations

import io
import uuid
from pathlib import Path

from conftest import requires_db
from inkloom_api.config import get_settings
from inkloom_api.models import AuditEvent, BrandSource, SourceVersion

DRAFT_TEXT = "Draft fact: the Verde lid is bamboo."


def _upload_draft(client, account, title: str = "Draft sheet") -> dict:
    response = client.post(
        f"/api/brands/{account.brand_id}/sources",
        data={"title": title, "approve": "false"},
        files={"file": ("draft.txt", io.BytesIO(DRAFT_TEXT.encode("utf-8")), "text/plain")},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "draft"
    return response.json()


def _source_ids(client, account) -> list[str]:
    return [s["id"] for s in client.get(f"/api/brands/{account.brand_id}/sources", headers=account.headers).json()]


@requires_db
def test_draft_source_is_deleted_with_its_versions_and_file(client, db_session, account_factory) -> None:
    owner = account_factory("owner")
    draft = _upload_draft(client, owner)
    row = db_session.get(BrandSource, uuid.UUID(draft["id"]))
    stored = Path(get_settings().brand_source_storage_dir) / row.storage_path
    assert stored.exists()

    deleted = client.delete(f"/api/brands/{owner.brand_id}/sources/{draft['id']}", headers=owner.headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"id": draft["id"], "title": "Draft sheet", "deleted": True}
    assert draft["id"] not in _source_ids(client, owner)
    db_session.expire_all()
    assert db_session.get(BrandSource, uuid.UUID(draft["id"])) is None
    assert db_session.query(SourceVersion).filter_by(brand_source_id=uuid.UUID(draft["id"])).count() == 0
    assert not stored.exists()

    [event] = db_session.query(AuditEvent).filter_by(event_type="brand_source.deleted", entity_id=draft["id"]).all()
    assert event.details == {"title": "Draft sheet", "status": "draft"}
    assert DRAFT_TEXT not in str(event.details)


@requires_db
def test_approved_and_withdrawn_sources_are_refused(client, account_factory) -> None:
    owner = account_factory("owner")  # uploads one approved fact sheet
    url = f"/api/brands/{owner.brand_id}/sources/{owner.source_id}"
    refused = client.delete(url, headers=owner.headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["message"] == (
        "only a document that was never approved can be deleted; withdraw an approved document instead"
    )
    assert owner.source_id in _source_ids(client, owner)

    withdrawn = client.post(f"{url}/withdraw", json={"status": "archived", "reason": "replaced"}, headers=owner.headers)
    assert withdrawn.status_code == 200, withdrawn.text
    assert client.delete(url, headers=owner.headers).status_code == 409
    assert owner.source_id in _source_ids(client, owner)


@requires_db
def test_another_accounts_source_is_not_found(client, account_factory) -> None:
    owner, other = account_factory("owner"), account_factory("other", with_source=False)
    draft = _upload_draft(client, owner)
    response = client.delete(f"/api/brands/{owner.brand_id}/sources/{draft['id']}", headers=other.headers)
    assert response.status_code == 404
    assert draft["id"] in _source_ids(client, owner)
