/**
 * Types for the INKLOOM backend (services/api). Checked by hand against the real response models
 * in services/api/src/inkloom_api/schemas.py and statuses.py, not only against API.md, which is
 * behind the code in places (see README "Backend contract notes").
 *
 * Status unions list every value the backend defines. `(string & {})` keeps them open so a value
 * added later still type-checks and is shown as-is instead of crashing a screen.
 */
type Open<T extends string> = T | (string & {});

export type Role = Open<
  "submitter" | "source_manager" | "reviewer" | "approver" | "admin" | "legal_reviewer" | "brand_manager"
>;

export type UserOut = { id: string; email: string; display_name: string | null };
export type OrganisationOut = { id: string; name: string; slug: string };

/** GET /api/auth/me */
export type SessionInfo = { user: UserOut; organisation: OrganisationOut; role: Role };

/** POST /api/auth/login */
export type LoginResponse = SessionInfo & { access_token: string; token_type: "bearer" };

export type BrandSourceStatus = Open<"draft" | "approved" | "superseded" | "archived">;
export type Sensitivity = Open<"normal" | "confidential">;

/** One item of GET /api/brands/{brand_id}/sources */
export type BrandSourceOut = {
  id: string;
  brand_profile_id: string;
  title: string;
  status: BrandSourceStatus;
  sensitivity: Sensitivity;
  /** Not in API.md; present in schemas.py. "txt" | "pdf" | "docx", null for seeded sources. */
  source_type: Open<"txt" | "pdf" | "docx"> | null;
  /** Not in API.md; present in schemas.py. */
  latest_version: number | null;
  created_at: string;
  updated_at: string;
};

export type ReviewState = Open<
  | "draft"
  | "queued"
  | "analysing"
  | "completed"
  | "needs_human_review"
  | "changes_requested"
  | "approved"
  | "rejected"
  | "failed"
  | "source_changed"
>;

export type VerificationStatus = Open<
  "supported" | "contradicted" | "unverified" | "conflicting_sources" | "not_applicable"
>;
export type Severity = Open<"low" | "medium" | "high" | "critical">;
export type CheckType = Open<"rule" | "retrieval" | "semantic">;
export type EvidenceRelation = Open<"supports" | "contradicts" | "context">;

/** Half-open [start, end) in Unicode CODE POINTS of the submitted text, not UTF-16 units. */
export type Span = { start: number; end: number };

export type EvidenceOut = {
  id: string;
  source_id: string | null;
  source_version_id: string | null;
  quote: string;
  relation: EvidenceRelation;
};

export type FindingOut = {
  finding_id: string;
  /** "stub" marks the placeholder finding returned when no AI provider is configured. */
  category: string | null;
  severity: Severity;
  original_text: string;
  span: Span;
  check_type: CheckType;
  explanation: string | null;
  verification_status: VerificationStatus;
  suggested_correction: string | null;
  requires_human_review: boolean;
  evidence: EvidenceOut[];
};

export type EngineInfo = {
  provider: string | null;
  model_id: string | null;
  prompt_version: string | null;
  contract_version: string | null;
};

/** POST /api/reviews and GET /api/reviews/{id} */
export type ReviewOut = {
  id: string;
  content_version_id: string;
  status: ReviewState;
  report_status: string | null;
  engine: EngineInfo | null;
  error_summary: string | null;
  /** Not in API.md; present in schemas.py (Phase 5 result cache). */
  served_from_cache: boolean;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  findings: FindingOut[];
  /** Not in API.md; present in schemas.py (Phase 9). */
  required_reviewer_role: Open<"legal_reviewer" | "brand_manager"> | null;
};

export type CreateReviewBody = { brand_id: string; title?: string; text: string };

export type ErrorCode = Open<
  "VALIDATION_ERROR" | "NOT_FOUND" | "UNAUTHENTICATED" | "FORBIDDEN" | "CONFLICT" | "RATE_LIMITED" | "INTERNAL_ERROR"
>;

/** Every backend error body: {"error": {"code", "message", "request_id"}} */
export type ErrorBody = { error: { code: ErrorCode; message: string; request_id: string } };
