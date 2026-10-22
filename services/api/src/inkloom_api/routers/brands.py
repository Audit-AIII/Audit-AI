"""GET /api/brands/{id}/sources — the one protected route Phase 2 implements end to end to
prove the auth + tenant-scoping pattern (task 6). Any active member of the organisation may
read brand sources; no specific permission is required (unlike creating/editing one, which
Phase 4 will gate on `manage_sources`)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth.dependencies import AuthContext, get_current_membership
from ..db import get_db
from ..models import BrandSource
from ..schemas import BrandSourceOut
from ..tenancy import get_brand_profile_or_404

router = APIRouter(prefix="/api/brands", tags=["brands"])


@router.get("/{brand_id}/sources", response_model=list[BrandSourceOut])
def list_brand_sources(
    brand_id: uuid.UUID,
    auth: AuthContext = Depends(get_current_membership),
    db: Session = Depends(get_db),
) -> list[BrandSource]:
    # organisation_id comes only from `auth`, never from the path or any query parameter — a
    # brand_id that belongs to another organisation is treated identically to one that doesn't
    # exist (tenancy.get_brand_profile_or_404).
    brand = get_brand_profile_or_404(db, auth.organisation_id, brand_id)
    return db.query(BrandSource).filter(BrandSource.brand_profile_id == brand.id).order_by(BrandSource.created_at).all()
