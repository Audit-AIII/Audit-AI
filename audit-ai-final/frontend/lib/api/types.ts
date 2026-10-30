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
  "owner" | "approver" | "reviewer" | "writer" | "submitter" | "source_manager" | "admin" | "legal_reviewer" | "brand_manager"
>;

export type UserOut = { id: string; email: string; display_name: string | null };
export type OrganisationOut = { id: string; name: string; slug: string };
/** Round 3 governance (docs/governance.md section 9). */
export type WorkspaceOut = { id: string; name: string; is_personal: boolean };
export type UserRef = { id: string; display_name: string };

/** GET /api/auth/me */
export type SessionInfo = { user: UserOut; organisation: OrganisationOut; role: Role; workspace?: WorkspaceOut };

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
  /** Why a person must decide; [] when no review is needed, null on rule and stub findings. */
  review_reasons?: string[] | null;
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
  required_reviewer_role: Open<"reviewer" | "approver" | "legal_reviewer" | "brand_manager"> | null;
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
  /* Round 3 governance (docs/governance.md 9.1); optional so an older backend still works. */
  workspace?: WorkspaceOut | null;
  author?: UserRef | null;
  owner?: UserRef | null;
  assigned_reviewer?: UserRef | null;
  workflow_status?: WorkflowStatus | null;
  risk_level?: RiskLevel | null;
  routing_reason?: RoutingReason | null;
  approval_mode?: Open<"team" | "self"> | null;
  /** What the current user may do, from the same rule the server enforces. Missing = older backend. */
  allowed_actions?: AllowedAction[];
  summary_counts?: SummaryCounts | null;
  is_current_version?: boolean | null;
};

export type WorkflowStatus = Open<
  "draft" | "submitted" | "in_review" | "needs_changes" | "reviewed" | "approved" | "rejected" | "published" | "blocked"
>;
export type RiskLevel = Open<"high" | "medium" | "low" | "clean">;
export type AllowedAction = Open<
  | "submit"
  | "resubmit"
  | "create_version"
  | "rerun"
  | "assign"
  | "mark_reviewed"
  | "request_changes"
  | "approve"
  | "reject"
  | "publish"
  | "comment"
  | "dismiss_finding"
>;
export type RoutingReason = {
  code: string;
  text: string;
  triggered_by?: { finding_id: string; verification_status: string; review_reasons: string[] | null; risk_level: string }[];
};
/** Counted by the server over this review's findings. `tone` only covers two style rules for now. */
export type SummaryCounts = {
  supported: number;
  contradicted: number;
  unverified: number;
  conflicting: number;
  tone: number;
  needs_human_review: number;
};

/** POST /api/content/{id}/submit, /assign, /mark-reviewed and /api/content-versions/{id}/publish */
export type WorkflowActionOut = {
  content_item_id: string;
  version_number: number | null;
  workflow_status: WorkflowStatus;
  risk_level: RiskLevel | null;
  required_reviewer_role: string | null;
  routing_reason: RoutingReason | null;
  assigned_reviewer: UserRef | null;
};

/** One audit entry. actor null = a system event. */
export type AuditEventOut = {
  id: string;
  actor: UserRef | null;
  action: string;
  event_type: string;
  note: string | null;
  version_number: number | null;
  created_at: string;
  details: Record<string, unknown> | null;
};
/** GET /api/content/{id}/audit */
export type AuditHistoryOut = { content_item_id: string; items: AuditEventOut[]; next_cursor: string | null };
/** GET /api/workspace/audit (owners) */
export type WorkspaceAuditOut = { items: AuditEventOut[]; next_cursor: string | null };

/** GET /api/workspace/members */
export type MemberOut = { user: UserRef; role: Role; is_you: boolean; joined_at: string };
export type MembersOut = { workspace: WorkspaceOut; members: MemberOut[]; allowed_actions: string[] };

export type InvitationOut = {
  id: string;
  email: string;
  role: Role;
  status: Open<"pending" | "accepted" | "revoked" | "expired">;
  invited_by: UserRef | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
};
/** POST /api/workspace/invitations. The token is shown once and never again. */
export type InvitationCreatedOut = { invitation: InvitationOut; token: string; accept_path: string };
export type InvitationsOut = { items: InvitationOut[] };

/** GET /api/workspaces */
export type WorkspaceMembershipOut = { workspace: WorkspaceOut; role: Role; is_current: boolean };

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
  | "VALIDATION_ERROR"
  | "NOT_FOUND"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "CONFLICT"
  | "RATE_LIMITED"
  | "INTERNAL_ERROR"
  | "SELF_APPROVAL_FORBIDDEN"
  | "SELF_REVIEW_FORBIDDEN"
  | "SAME_REVIEWER_APPROVER_FORBIDDEN"
  | "SELF_ROLE_CHANGE_FORBIDDEN"
  | "ROLE_ESCALATION_FORBIDDEN"
  | "INVITE_EMAIL_MISMATCH"
  | "REVIEW_REQUIRED"
  | "INVALID_TRANSITION"
  | "INVITE_EXPIRED"
  | "INVITE_REVOKED"
  | "INVITE_ALREADY_USED"
  | "INVITE_ALREADY_PENDING"
  | "ALREADY_MEMBER"
  | "LAST_OWNER_REQUIRED"
>;

/** Every backend error body: {"error": {"code", "message", "request_id"}} */
export type ErrorBody = { error: { code: ErrorCode; message: string; request_id: string } };
