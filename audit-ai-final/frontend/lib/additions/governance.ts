import type { AllowedAction } from "../api/types";

/**
 * Words, glyphs and tones for governance values (docs/governance.md section 9), plus the one rule
 * for reading allowed_actions. Pure, so qa/unit can test it. Status is never colour alone.
 */
export type Look = { glyph: string; label: string; tone: string };

const words = (s: string) => s.replace(/[_.]/g, " ").replace(/^\w/, (c) => c.toUpperCase());

const WORKFLOW: Record<string, Look> = {
  draft: { glyph: "…", label: "Draft", tone: "dashed" },
  submitted: { glyph: "→", label: "Submitted", tone: "warn" },
  in_review: { glyph: "●", label: "In review", tone: "warn" },
  needs_changes: { glyph: "↩", label: "Needs changes", tone: "warn" },
  reviewed: { glyph: "○", label: "Reviewed", tone: "dashed" },
  approved: { glyph: "✓", label: "Approved", tone: "ok" },
  rejected: { glyph: "≠", label: "Rejected", tone: "bad" },
  published: { glyph: "✓✓", label: "Published", tone: "ok" },
  blocked: { glyph: "⊘", label: "Blocked", tone: "bad" },
};
/** Unknown values read "In progress" (docs/governance.md 9.1); a missing value isn't a status at all. */
export const workflowLook = (status?: string | null): Look =>
  status ? (WORKFLOW[status] ?? { glyph: "…", label: "In progress", tone: "dashed" }) : { glyph: "–", label: "Not provided", tone: "dashed" };

const RISK: Record<string, Look> = {
  high: { glyph: "●●●", label: "High", tone: "bad" },
  medium: { glyph: "●●○", label: "Medium", tone: "warn" },
  low: { glyph: "●○○", label: "Low", tone: "ok" },
  clean: { glyph: "○○○", label: "None found", tone: "none" },
};
/** null until the AI check finishes. */
export const riskLook = (level?: string | null): Look =>
  level ? (RISK[level] ?? { glyph: "?", label: words(level), tone: "dashed" }) : { glyph: "–", label: "Not assessed yet", tone: "dashed" };

const ROLE: Record<string, Look> = {
  owner: { glyph: "◆", label: "Owner", tone: "rule" },
  admin: { glyph: "◆", label: "Owner", tone: "rule" }, // legacy name for owner
  approver: { glyph: "✓", label: "Approver", tone: "rule" },
  reviewer: { glyph: "○", label: "Reviewer", tone: "rule" },
  writer: { glyph: "…", label: "Writer", tone: "rule" },
};
export const roleLook = (role: string): Look => ROLE[role] ?? { glyph: "?", label: words(role), tone: "rule" };

const INVITATION: Record<string, Look> = {
  pending: { glyph: "…", label: "Pending", tone: "warn" },
  accepted: { glyph: "✓", label: "Accepted", tone: "ok" },
  revoked: { glyph: "⊘", label: "Revoked", tone: "dashed" },
  expired: { glyph: "–", label: "Expired", tone: "dashed" },
};
export const invitationLook = (status: string): Look => INVITATION[status] ?? { glyph: "?", label: words(status), tone: "dashed" };

const AUDIT: Record<string, Pick<Look, "glyph" | "label">> = {
  draft_created: { glyph: "…", label: "Draft created" },
  version_created: { glyph: "…", label: "New version saved" },
  recheck_requested: { glyph: "↻", label: "Checked again" },
  locks_updated: { glyph: "🔒", label: "Protected phrases changed" },
  approval_granted: { glyph: "✓", label: "Approved" },
  approval_rejected: { glyph: "≠", label: "Rejected" },
  changes_requested: { glyph: "↩", label: "Sent back for changes" },
  source_changed: { glyph: "↻", label: "A cited document changed" },
  evidence_rejected: { glyph: "≠", label: "Evidence failed its check" },
  finding_dismissed: { glyph: "⊖", label: "Finding dismissed" },
  finding_restored: { glyph: "↺", label: "Finding restored" },
  finding_commented: { glyph: "…", label: "Comment added" },
  draft_submitted: { glyph: "→", label: "Sent for review" },
  routing_decision: { glyph: "→", label: "Routing decision" },
  review_requested: { glyph: "●", label: "Review requested" },
  reviewer_assigned: { glyph: "●", label: "Reviewer assigned" },
  reviewed: { glyph: "○", label: "Marked as reviewed" },
  approval_denied: { glyph: "⊘", label: "Approval refused" },
  published: { glyph: "✓✓", label: "Marked as published" },
  "account.registered": { glyph: "◆", label: "Account registered" },
  invite_created: { glyph: "→", label: "Invitation created" },
  invite_accepted: { glyph: "✓", label: "Invitation accepted" },
  invite_revoked: { glyph: "⊘", label: "Invitation revoked" },
  member_role_changed: { glyph: "●", label: "Role changed" },
  member_removed: { glyph: "⊖", label: "Member removed" },
};
/** Unknown actions are passed through by the server, so they stay readable here. */
export const auditLook = (action: string) => AUDIT[action] ?? { glyph: "·", label: words(action) };

/** The before and after status an audit event carries, if any. Nothing else in details is shown. */
export function statusChange(details: Record<string, unknown> | null | undefined) {
  const status = (side: unknown) => (side as { workflow_status?: unknown } | null | undefined)?.workflow_status;
  const before = status(details?.before);
  const after = status(details?.after);
  return typeof before === "string" && typeof after === "string" ? { before, after } : null;
}

/**
 * Is this person alone here? workspace.is_personal can't say: it stays true after someone joins.
 * workspace.member_count can. An older backend doesn't send it, so its other fields are the best guide.
 */
export const isSolo = (review: { workspace?: { is_personal: boolean; member_count?: number | null } | null; approval_mode?: string | null }) => {
  const members = review.workspace?.member_count;
  return members != null ? members <= 1 : (review.workspace?.is_personal ?? true) && review.approval_mode !== "team";
};

export const isOwner = (role: string | undefined) => role === "owner" || role === "admin"; // admin: legacy name

/**
 * May this control be drawn? Missing allowed_actions means an older backend, so today's behaviour
 * stays; an empty list means nothing is allowed. The server still has the last word.
 */
export const isAllowed = (allowed: readonly AllowedAction[] | undefined | null, action: AllowedAction) =>
  allowed == null ? true : allowed.includes(action);

/**
 * The API's routing text ends "..., so a reviewer must check this draft before it can be approved."
 * With solo sign-off there is no reviewer, so keep the reason and drop what isn't true for them.
 */
export const routingText = (text: string, solo: boolean) => (solo ? text.replace(/, so an? \w+ must .*$/, ".") : text);

const ACTION_ERROR: Record<string, string> = {
  SELF_APPROVAL_FORBIDDEN: "You wrote this draft, so someone else has to approve it.",
  SELF_REVIEW_FORBIDDEN: "You wrote this draft, so someone else has to review it.",
  SAME_REVIEWER_APPROVER_FORBIDDEN: "You reviewed this version, so a different person has to approve it.",
  SELF_ROLE_CHANGE_FORBIDDEN: "You can’t change your own role. Ask another owner to do it.",
  ROLE_ESCALATION_FORBIDDEN: "You can’t give someone a role you don’t hold yourself.",
  INVITE_EMAIL_MISMATCH: "This invitation was sent to a different email address. Sign in with that address to accept it.",
  REVIEW_REQUIRED: "This draft has to be reviewed before it can be approved.",
  INVITE_EXPIRED: "This invitation has expired. Ask for a new one.",
  INVITE_REVOKED: "This invitation was withdrawn. Ask for a new one if you still need access.",
  INVITE_ALREADY_USED: "This invitation has already been accepted.",
  INVITE_ALREADY_PENDING: "An invitation for this email is already waiting. Revoke it first to send a new one.",
  ALREADY_MEMBER: "This person is already in the workspace.",
  LAST_OWNER_REQUIRED: "A workspace must keep at least one owner. Make someone else an owner first.",
};
const sentence = (s: string) => {
  const t = s.replace(/^\w/, (c) => c.toUpperCase());
  return /[.!?]$/.test(t) ? t : `${t}.`;
};
/**
 * Text for a refused action. A 403 or 409 explains the rule that stopped it, so the API's own message
 * is kept when there's no plainer wording. Network, rate-limit and server failures use `fallback`
 * (ApiError.userMessage), because their raw messages mean nothing to a reader.
 */
export const actionErrorText = (e: { status: number; code: string; message: string }, fallback: string) =>
  ACTION_ERROR[e.code] ?? ([403, 404, 409, 422].includes(e.status) ? sentence(e.message) : fallback);
