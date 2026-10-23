"""Brand source listing, upload and approval.

`GET /api/brands/{id}/sources` (Phase 2) needs no specific permission — any active member may
read. `POST .../sources` and `.../approve` (Phase 4) are gated on `manage_sources`: only
`source_manager` and `admin` hold it (see contract/README.md, "Role names").
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from inkloom_verify.schemas import ReferenceDocument
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, BrandSource, SourceVersion
from ..schemas import BrandSourceOut, FlippedDependentOut, NewSourceVersionResponse, WithdrawSourceResponse
from ..section_diff import document_section_hashes
from ..source_lifecycle import apply_new_version_diff, withdraw_source
from ..source_upload import extract_text, file_type_from_name, read_limited, store_upload
from ..statuses import BrandSourceSensitivity, BrandSourceStatus
from ..tenancy import get_brand_profile_or_404, get_brand_source_or_404

router = APIRouter(prefix="/api/brands", tags=["brands"])


@router.get("/{brand_id}/sources", response_model=list[BrandSourceOut])
def list_brand_sources(
    brand_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[BrandSourceOut]:
    # organisation_id comes only from `auth`, never from the path or any query parameter — a
    # brand_id that belongs to another organisation is treated identically to one that doesn't
    # exist (tenancy.get_brand_profile_or_404).
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    sources = (
        db.query(BrandSource).filter(BrandSource.brand_profile_id == brand.id).order_by(BrandSource.created_at).all()
    )
    return [BrandSourceOut.from_model(s) for s in sources]


@router.post("/{brand_id}/sources", response_model=BrandSourceOut, status_code=201)
def upload_brand_source(
    brand_id: uuid.UUID,
    title: str = Form(..., max_length=300),
    sensitivity: str = Form(BrandSourceSensitivity.NORMAL.value),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BrandSourceOut:
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    if sensitivity not in (BrandSourceSensitivity.NORMAL.value, BrandSourceSensitivity.CONFIDENTIAL.value):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "sensitivity must be 'normal' or 'confidential'")

    file_type = file_type_from_name(file.filename)
    content = read_limited(file, settings.max_source_upload_bytes)
    text = extract_text(file_type, content)
    storage_path = store_upload(settings, auth.organisation_id, file_type, content)

    source = BrandSource(
        brand_profile_id=brand.id,
        title=title,
        status=BrandSourceStatus.DRAFT.value,  # always draft until explicitly approved (task 3)
        sensitivity=sensitivity,
        source_type=file_type.value,
        storage_path=storage_path,
        created_by=auth.user_id,
    )
    db.add(source)
    db.flush()

    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    db.add(
        SourceVersion(
            brand_source_id=source.id,
            version_number=1,
            text=text,
            text_sha256=text_sha256,
            section_hashes=document_section_hashes(
                ReferenceDocument(doc_id=str(source.id), text=text, text_sha256=text_sha256)
            ),
            created_by=auth.user_id,
        )
    )
    db.add(
        AuditEvent(
            organisation_id=auth.organisation_id,
            actor_user_id=auth.user_id,
            event_type="brand_source.uploaded",
            entity_type="brand_source",
            entity_id=str(source.id),
            details={"source_type": file_type.value, "sensitivity": sensitivity},
        )
    )
    db.commit()
    db.refresh(source)
    return BrandSourceOut.from_model(source)


class WithdrawSourceBody(BaseModel):
    status: Literal["superseded", "archived"]
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/{brand_id}/sources/{source_id}/withdraw", response_model=WithdrawSourceResponse)
def withdraw_brand_source(
    brand_id: uuid.UUID,
    source_id: uuid.UUID,
    body: WithdrawSourceBody,
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
) -> WithdrawSourceResponse:
    """Phase 7 task 3: withdrawing an approved source flips every approved item that cited it
    to `source_changed` and sends it back to the reviewer queue with a drift reason."""
    source = get_brand_source_or_404(db, auth.organisation_id, brand_id, source_id)
    if source.status != BrandSourceStatus.APPROVED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "only an approved source can be withdrawn")

    flipped = withdraw_source(db, source, body.status, body.reason, auth.organisation_id, auth.user_id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="brand_source.withdrawn",
        entity_type="brand_source",
        entity_id=source.id,
        details={"new_status": body.status, "reason": body.reason, "dependents_flipped": len(flipped)},
    )
    db.commit()
    db.refresh(source)
    return WithdrawSourceResponse(
        source=BrandSourceOut.from_model(source),
        reason=body.reason,
        flipped=[FlippedDependentOut(**f) for f in flipped],
    )


@router.post("/{brand_id}/sources/{source_id}/versions", response_model=NewSourceVersionResponse, status_code=201)
def upload_new_source_version(
    brand_id: uuid.UUID,
    source_id: uuid.UUID,
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> NewSourceVersionResponse:
    """Phase 7 task 4: a new version of an EXISTING source. Unlike withdraw, this only flips a
    dependent whose evidence cited a section that didn't survive into the new text, verbatim.
    The source's own status is left as-is - updating an approved source's content doesn't
    silently re-approve or un-approve it; that's a separate, deliberate action."""
    source = get_brand_source_or_404(db, auth.organisation_id, brand_id, source_id)

    file_type = file_type_from_name(file.filename)
    content = read_limited(file, settings.max_source_upload_bytes)
    text = extract_text(file_type, content)
    storage_path = store_upload(settings, auth.organisation_id, file_type, content)
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()

    next_number = (
        db.query(SourceVersion.version_number)
        .filter_by(brand_source_id=source.id)
        .order_by(SourceVersion.version_number.desc())
        .first()[0]
        + 1
    )
    new_version = SourceVersion(
        brand_source_id=source.id,
        version_number=next_number,
        text=text,
        text_sha256=text_sha256,
        section_hashes=document_section_hashes(
            ReferenceDocument(doc_id=str(source.id), text=text, text_sha256=text_sha256)
        ),
        created_by=auth.user_id,
    )
    db.add(new_version)
    db.flush()
    source.storage_path = storage_path  # the file on disk the source was last updated from
    source.source_type = file_type.value

    flipped = apply_new_version_diff(db, source, new_version, auth.organisation_id, auth.user_id)
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="brand_source.new_version_uploaded",
        entity_type="brand_source",
        entity_id=source.id,
        details={"version_number": next_number, "dependents_flipped": len(flipped)},
    )
    db.commit()
    db.refresh(source)
    db.refresh(new_version)
    return NewSourceVersionResponse(
        source=BrandSourceOut.from_model(source),
        version_number=new_version.version_number,
        flipped=[FlippedDependentOut(**f) for f in flipped],
    )


@router.post("/{brand_id}/sources/{source_id}/approve", response_model=BrandSourceOut)
def approve_brand_source(
    brand_id: uuid.UUID,
    source_id: uuid.UUID,
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
) -> BrandSourceOut:
    source = get_brand_source_or_404(db, auth.organisation_id, brand_id, source_id)
    previous_status = source.status
    source.status = BrandSourceStatus.APPROVED.value
    db.add(
        AuditEvent(
            organisation_id=auth.organisation_id,
            actor_user_id=auth.user_id,
            event_type="brand_source.approved",
            entity_type="brand_source",
            entity_id=str(source.id),
            details={"previous_status": previous_status},
        )
    )
    db.commit()
    db.refresh(source)
    return BrandSourceOut.from_model(source)
