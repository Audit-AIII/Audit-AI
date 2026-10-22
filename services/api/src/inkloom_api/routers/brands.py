"""Brand source listing, upload and approval.

`GET /api/brands/{id}/sources` (Phase 2) needs no specific permission — any active member may
read. `POST .../sources` and `.../approve` (Phase 4) are gated on `manage_sources`: only
`source_manager` and `admin` hold it (see contract/README.md, "Role names").
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, BrandSource, SourceVersion
from ..schemas import BrandSourceOut
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

    db.add(
        SourceVersion(
            brand_source_id=source.id,
            version_number=1,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
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
