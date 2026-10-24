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
export type LoginResponse = SessionInfo & {
  access_token: string;
  token_type: "bearer";
  /** Seconds until the token expires. New in the onboarding contract; optional until the backend sends it. */
  expires_in?: number;
};

/** GET /api/brands (oldest first), POST /api/brands */
export type BrandOut = {
  id: string;
  name: string;
  description: string | null;
  approved_source_count: number;
  created_at: string;
};

/** POST /api/auth/register. Password: 8+ characters, at most 72 bytes (bcrypt limit). */
export type RegisterBody = {
  email: string;
  password: string;
  display_name?: string;
  brand_name?: string;
  organisation_name?: string;
};

/** The new user is admin of a new organisation with one brand. */
export type RegisterResponse = LoginResponse & { brand: BrandOut };

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
  /** The document and version the quote was taken from (optional; newer backends). */
  source_title?: string | null;
  source_version_number?: number | null;
};

/* ---- Brand rules (services/api/API.md "Brand rules" / "Rule findings"; contract/README.md) ---- */

export type RuleCategory = Open<"terminology" | "brand_compliance" | "accessibility">;
export type RuleType = Open<
  | "required_term" | "prohibited_term" | "product_naming" | "preferred_term" | "spelling" | "terminology_consistency"
  | "required_disclaimer" | "numeric_limit"
  | "all_caps_run" | "emoji_run" | "vague_link_text" | "missing_alt_text" | "heading_structure" | "missing_captions" | "low_contrast"
>;
/** "text": about the highlighted span. "document": something is missing from the whole draft. */
export type RuleScope = Open<"text" | "document">;
export type SuggestionBasis = Open<"brand_rule" | "approved_document">;
export type RulesStatus = Open<"complete" | "incomplete" | "not_applied">;
/** "not_checkable" = nothing to inspect (no links, headings, images...): show "Not checked", never "Passed". */
export type RuleCheckStatus = Open<"passed" | "violated" | "not_checkable" | "error">;
export type RuleCheck = {
  rule_id: string;
  rule_type: RuleType;
  category: RuleCategory;
  status: RuleCheckStatus;
  findings: number;
  reason: string | null;
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
  /* Rule findings only (check_type "rule"); null on claim findings, absent on older backends. */
  rule_id?: string | null;
  rule_type?: RuleType | null;
  scope?: RuleScope | null;
  suggestion_basis?: SuggestionBasis | null;
  source_ids?: string[] | null;
  /** Unverified claims only: a softened rewrite that is NOT backed by evidence (suggested_correction
   * stays empty for unverified claims on backends that send this). */
  safer_wording?: string | null;
  /** Intent-lock: a stored suggestion was hidden on read because it would remove a locked phrase
   * (suggested_correction / safer_wording are then null). Re-run for one that keeps the locks. */
  withheld_by_intent_lock?: boolean;
  /** Set while the finding is dismissed. Dismissed is NOT "supported": the verdict is unchanged. */
  dismissal?: DismissalOut | null;
  comment_count?: number;
};

/* ---- Dismiss, comments, Intent-lock (API.md "Dismiss and comments" / "Intent-lock";
   routers/findings.py, routers/content_versions.py, schemas.py DismissalOut) ---- */

/** On a finding while it is dismissed. */
export type DismissalOut = { by_user_id: string | null; at: string; note: string | null };
/** POST /api/findings/{id}/dismiss and /restore (201). */
export type FindingDecision = {
  id: string;
  finding_id: string;
  action: Open<"dismissed" | "restored">;
  note: string | null;
  actor_user_id: string | null;
  created_at: string;
};
/** GET /api/findings/{id}/comments (oldest first) and POST (201). */
export type FindingComment = { id: string; finding_id: string; author_user_id: string | null; body: string; created_at: string };
/** GET / PUT /api/content-versions/{id}/locks. */
export type LocksOut = { content_version_id: string; locked_phrases: string[] };

/** findings.py DecisionBody.note / CommentBody.body max_length; intent_lock.py MAX_LOCKS / MAX_LOCK_CHARS. */
export const NOTE_MAX = 2000;
export const COMMENT_MAX = 2000;
export const LOCKS_MAX = 50;
export const LOCK_MAX_CHARS = 200;

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
  /* Onboarding contract additions; optional until the backend sends them. */
  content_item_id?: string | null;
  brand_id?: string | null;
  title?: string | null;
  version_number?: number | null;
  /** The submitted (or extracted) text the spans point into. */
  text?: string | null;
  /** Brand rules: complete | incomplete | not_applied; null on reviews from before rules existed. */
  rules_status?: RulesStatus | null;
  /** One record per rule that ran; null when the rules did not run. */
  rule_checks?: RuleCheck[] | null;
  /** Intent-lock list of the reviewed content version; null/absent on older backends. */
  locked_phrases?: string[] | null;
};

/** Stored brand rules (BrandRules, services/verification/schemas/brand_rules.schema.json).
 * rule_set_id / version are set by the server and are never sent on PUT. */
export type BrandRules = Record<string, unknown> & { rule_set_id?: string; version?: string | null };
/** GET / PUT /api/brands/{id}/rules */
export type BrandRulesOut = { brand_id: string; rules: BrandRules | null };

/** POST /api/content-versions/{id}/approve and /request-changes */
export type ApprovalEventOut = {
  id: string;
  content_version_id: string;
  version_number: number | null;
  action: Open<"approved" | "rejected" | "changes_requested">;
  actor_user_id: string;
  note: string | null;
  created_at: string;
};

/** Body of POST /api/content-versions/{id}/request-changes (note: max 2000 characters). */
export type RequestChangesBody = { decision: "changes_requested" | "rejected"; note?: string };

export type CreateReviewBody = { brand_id: string; title?: string; text: string };

export type ErrorCode = Open<
  "VALIDATION_ERROR" | "NOT_FOUND" | "UNAUTHENTICATED" | "FORBIDDEN" | "CONFLICT" | "RATE_LIMITED" | "INTERNAL_ERROR"
>;

/** Every backend error body: {"error": {"code", "message", "request_id"}} */
export type ErrorBody = { error: { code: ErrorCode; message: string; request_id: string } };
