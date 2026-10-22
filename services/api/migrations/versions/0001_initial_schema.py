"""Initial schema: tenancy, brand knowledge, content, reviews, findings, governance, audit, ops.

See member3_backend/phase1_foundation_and_contract.md task 2-4, and
services/api/src/inkloom_api/statuses.py for the status strings enforced by the CHECK
constraints below.

Revision ID: 0001
Revises:
Create Date: 2026-10-22

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MEMBERSHIP_ROLES = ("submitter", "source_manager", "reviewer", "approver", "admin")
BRAND_SOURCE_STATUSES = ("draft", "approved", "superseded", "archived")
BRAND_SOURCE_SENSITIVITIES = ("normal", "confidential")
REVIEW_STATES = (
    "draft",
    "queued",
    "analysing",
    "completed",
    "needs_human_review",
    "changes_requested",
    "approved",
    "rejected",
    "failed",
    "source_changed",
)
SEVERITIES = ("low", "medium", "high", "critical")
CHECK_TYPES = ("rule", "retrieval", "semantic")
VERIFICATION_STATUSES = ("supported", "contradicted", "unverified", "conflicting_sources", "not_applicable")
EVIDENCE_RELATIONS = ("supports", "contradicts", "context")
APPROVAL_ACTIONS = ("approved", "rejected", "changes_requested")
EXTERNAL_CALL_STATUSES = ("success", "error", "timeout", "rate_limited")


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200)),
        sa.Column("password_hash", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "user_id", name="uq_membership_org_user"),
        sa.CheckConstraint(f"role IN {MEMBERSHIP_ROLES}", name="ck_membership_role"),
    )
    op.create_index("ix_memberships_organisation_id", "memberships", ["organisation_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "brand_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "name", name="uq_brand_profile_org_name"),
    )
    op.create_index("ix_brand_profiles_organisation_id", "brand_profiles", ["organisation_id"])

    op.create_table(
        "brand_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brand_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brand_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("sensitivity", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {BRAND_SOURCE_STATUSES}", name="ck_brand_source_status"),
        sa.CheckConstraint(f"sensitivity IN {BRAND_SOURCE_SENSITIVITIES}", name="ck_brand_source_sensitivity"),
    )
    op.create_index("ix_brand_sources_brand_profile_id", "brand_sources", ["brand_profile_id"])

    op.create_table(
        "source_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "brand_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("brand_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("brand_source_id", "version_number", name="uq_source_version_number"),
    )
    op.create_index("ix_source_versions_brand_source_id", "source_versions", ["brand_source_id"])

    op.create_table(
        "content_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_items_organisation_id", "content_items", ["organisation_id"])

    op.create_table(
        "content_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "content_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_item_id", "version_number", name="uq_content_version_number"),
    )
    op.create_index("ix_content_versions_content_item_id", "content_versions", ["content_item_id"])

    op.create_table(
        "reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "content_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column("engine_provider", sa.String(100)),
        sa.Column("engine_model_id", sa.String(100)),
        sa.Column("prompt_version", sa.String(50)),
        sa.Column("engine_contract_version", sa.String(20)),
        sa.Column("request_id", sa.String(128)),
        sa.Column("report_status", sa.String(20)),
        sa.Column("error_summary", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {REVIEW_STATES}", name="ck_review_status"),
    )
    op.create_index("ix_reviews_content_version_id", "reviews", ["content_version_id"])
    op.create_index("ix_reviews_request_id", "reviews", ["request_id"])

    op.create_table(
        "findings",
        sa.Column("finding_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("category", sa.String(100)),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("original_text", sa.Text, nullable=False),
        sa.Column("span_start", sa.Integer, nullable=False),
        sa.Column("span_end", sa.Integer, nullable=False),
        sa.Column("check_type", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("suggested_correction", sa.Text),
        sa.Column("requires_human_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("engine_claim_id", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("span_end > span_start", name="ck_finding_span_order"),
        sa.CheckConstraint(f"severity IN {SEVERITIES}", name="ck_finding_severity"),
        sa.CheckConstraint(f"check_type IN {CHECK_TYPES}", name="ck_finding_check_type"),
        sa.CheckConstraint(f"verification_status IN {VERIFICATION_STATUSES}", name="ck_finding_verification_status"),
    )
    op.create_index("ix_findings_review_id", "findings", ["review_id"])

    op.create_table(
        "evidence_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "finding_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("findings.finding_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("brand_sources.id")),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("source_versions.id")),
        sa.Column("quote", sa.Text, nullable=False),
        sa.Column("relation", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"relation IN {EVIDENCE_RELATIONS}", name="ck_evidence_relation"),
    )
    op.create_index("ix_evidence_links_finding_id", "evidence_links", ["finding_id"])

    op.create_table(
        "approval_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "content_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id")),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"action IN {APPROVAL_ACTIONS}", name="ck_approval_action"),
    )
    op.create_index("ix_approval_events_content_version_id", "approval_events", ["content_version_id"])
    op.create_index("ix_approval_events_actor_user_id", "approval_events", ["actor_user_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("details", postgresql.JSONB),
        sa.Column("request_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_organisation_id", "audit_events", ["organisation_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])

    op.create_table(
        "external_call_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id")),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(100)),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("error_code", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN {EXTERNAL_CALL_STATUSES}", name="ck_external_call_status"),
    )
    op.create_index("ix_external_call_log_organisation_id", "external_call_log", ["organisation_id"])
    op.create_index("ix_external_call_log_request_id", "external_call_log", ["request_id"])

    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_body", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "endpoint", "key", name="uq_idempotency_org_endpoint_key"),
    )
    op.create_index("ix_idempotency_keys_organisation_id", "idempotency_keys", ["organisation_id"])

    op.create_table(
        "result_cache",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(128), nullable=False, unique=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id")),
        sa.Column("report", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("result_cache")
    op.drop_table("idempotency_keys")
    op.drop_table("external_call_log")
    op.drop_table("audit_events")
    op.drop_table("approval_events")
    op.drop_table("evidence_links")
    op.drop_table("findings")
    op.drop_table("reviews")
    op.drop_table("content_versions")
    op.drop_table("content_items")
    op.drop_table("source_versions")
    op.drop_table("brand_sources")
    op.drop_table("brand_profiles")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organisations")
