"""Brand listing/creation, brand source listing, upload and approval.

Individual-user mode: each organisation is one user's private account, so `GET /api/brands` is
that user's dashboard list of their own brands. Write routes keep `require_permission(...)`,
which every active membership now satisfies (auth/permissions.py) - the access rule that matters
is that every brand/source lookup is scoped to the caller's own account (tenancy.py: 404
otherwise, never a hint that another account's brand exists).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from inkloom_verify.schemas import ReferenceDocument
from inkloom_verify.schemas import BrandRules
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import log_audit_event
from ..auth.dependencies import AuthContext, get_current_membership, require_permission
from ..auth.permissions import Permission
from ..config import Settings, get_settings
from ..db import get_db
from ..models import AuditEvent, BrandProfile, BrandSource, SourceVersion
from ..request_text import StoredText, contains_nul
from ..review_queries import brand_review_stats
from ..schemas import BrandOut, BrandSourceOut, FlippedDependentOut, NewSourceVersionResponse, WithdrawSourceResponse
from ..section_diff import document_section_hashes
from ..source_lifecycle import apply_new_version_diff, withdraw_source
from ..source_upload import extract_text, file_type_from_name, read_limited, store_upload
from ..statuses import BrandSourceSensitivity, BrandSourceStatus
from ..tenancy import get_brand_profile_or_404, get_brand_source_or_404

router = APIRouter(prefix="/api/brands", tags=["brands"])

_DUPLICATE_BRAND_NAME = "a brand with this name already exists"


def _approved_source_counts(db: Session, organisation_id: uuid.UUID) -> dict[uuid.UUID, int]:
    rows = (
        db.query(BrandSource.brand_profile_id, func.count(BrandSource.id))
        .join(BrandProfile, BrandSource.brand_profile_id == BrandProfile.id)
        .filter(
            BrandProfile.organisation_id == organisation_id,
            BrandSource.status == BrandSourceStatus.APPROVED.value,
        )
        .group_by(BrandSource.brand_profile_id)
        .all()
    )
    return dict(rows)


@router.get("", response_model=list[BrandOut])
def list_brands(
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[BrandOut]:
    brands = (
        db.query(BrandProfile)
        .filter(BrandProfile.organisation_id == auth.organisation_id)
        .order_by(BrandProfile.created_at, BrandProfile.name)
        .all()
    )
    counts = _approved_source_counts(db, auth.organisation_id)  # one GROUP BY query, not N+1
    stats = brand_review_stats(db, auth.organisation_id)  # two more GROUP BYs, still not N+1
    return [
        BrandOut(
            id=brand.id,
            name=brand.name,
            description=brand.description,
            approved_source_count=counts.get(brand.id, 0),
            created_at=brand.created_at,
            **stats.get(brand.id, {}),  # absent -> the schema's zeros / null, never invented
        )
        for brand in brands
    ]


class BrandCreateRequest(BaseModel):
    name: StoredText = Field(min_length=1, max_length=200)
    description: StoredText | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @field_validator("description", mode="before")
    @classmethod
    def _blank_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


@router.post("", response_model=BrandOut, status_code=201)
def create_brand(
    body: BrandCreateRequest,
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
) -> BrandOut:
    # organisation_id comes only from the token - a caller can never create a brand in another
    # tenant's organisation by passing one in the body (there is no such field to pass).
    brand = BrandProfile(organisation_id=auth.organisation_id, name=body.name, description=body.description)
    db.add(brand)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, _DUPLICATE_BRAND_NAME) from None

    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="brand.created",
        entity_type="brand_profile",
        entity_id=brand.id,
        details={"name": brand.name},
    )
    db.commit()
    db.refresh(brand)
    return BrandOut(
        id=brand.id, name=brand.name, description=brand.description, approved_source_count=0, created_at=brand.created_at
    )


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
    # Annotated form: FastAPI skips StoredText's validator on a required `= Form(...)` default.
    title: Annotated[StoredText, Form(max_length=300)],
    sensitivity: str = Form(BrandSourceSensitivity.NORMAL.value),
    approve: bool = Form(False),
    file: UploadFile = File(...),
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> BrandSourceOut:
    """Self-serve onboarding uploads its one brand-fact PDF with `approve=true` so it's
    immediately usable by a review in the same step - safe because this route already requires
    `manage_sources` (the same permission `.../approve` requires); the default (`False`) is
    unchanged for every other caller."""
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
        status=BrandSourceStatus.APPROVED.value if approve else BrandSourceStatus.DRAFT.value,
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
    if approve:
        db.add(
            AuditEvent(
                organisation_id=auth.organisation_id,
                actor_user_id=auth.user_id,
                event_type="brand_source.approved",
                entity_type="brand_source",
                entity_id=str(source.id),
                details={"previous_status": "draft", "approved_on_upload": True},
            )
        )
    db.commit()
    db.refresh(source)
    return BrandSourceOut.from_model(source)


class WithdrawSourceBody(BaseModel):
    status: Literal["superseded", "archived"]
    reason: StoredText = Field(min_length=1, max_length=2000)


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


# --- Brand rules (terminology, compliance, accessibility; migration 0010) -----------------------


class BrandRulesRequest(BaseModel):
    # An `inkloom_verify.schemas.BrandRules` object without `rule_set_id`/`version` (this backend
    # sets both), or null to remove the brand's rules (the default accessibility checks still run).
    rules: dict | None


class BrandRulesOut(BaseModel):
    brand_id: uuid.UUID
    rules: dict | None


@router.get("/{brand_id}/rules", response_model=BrandRulesOut)
def get_brand_rules(
    brand_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> BrandRulesOut:
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    return BrandRulesOut(brand_id=brand.id, rules=brand.rules)


@router.put("/{brand_id}/rules", response_model=BrandRulesOut)
def put_brand_rules(
    brand_id: uuid.UUID,
    body: BrandRulesRequest,
    auth: AuthContext = Depends(require_permission(Permission.MANAGE_SOURCES)),
    db: Session = Depends(get_db),
) -> BrandRulesOut:
    """Validated with the engine's own `BrandRules` when saved (RULES_HANDOFF.md section 4), so a
    malformed or contradictory rule set is a 422 here - naming fields and rule ids, never values -
    rather than a review that can't apply it. Each save bumps `version`; reviews read the rules
    as they are when the review runs."""
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    stored = None
    if body.rules is not None:
        if contains_nul(body.rules):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "invalid brand rules: must not contain NUL (0x00) characters")
        previous = (brand.rules or {}).get("version")
        version = int(previous) + 1 if isinstance(previous, str) and previous.isdigit() else 1
        candidate = {**body.rules, "rule_set_id": f"brand-{brand.id}", "version": str(version)}
        try:
            validated = BrandRules.model_validate(candidate)
        except ValidationError as error:
            problems = [(".".join(str(p) for p in e["loc"]) or "rules") + ": " + e["msg"] for e in error.errors()][:20]
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid brand rules: {'; '.join(problems)}"[:1000]) from None
        stored = validated.model_dump(mode="json", exclude_unset=True)

    brand.rules = stored
    log_audit_event(
        db,
        organisation_id=auth.organisation_id,
        actor_user_id=auth.user_id,
        event_type="brand.rules_updated" if stored is not None else "brand.rules_cleared",
        entity_type="brand_profile",
        entity_id=brand.id,
        details={"version": stored["version"]} if stored is not None else {},
    )
    db.commit()
    return BrandRulesOut(brand_id=brand.id, rules=stored)
