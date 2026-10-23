/** Mirrors services/api auth/permissions.py. The server still enforces every rule; this only
 * decides which buttons to offer and how to explain a disabled one. */
const APPROVERS = new Set(["approver", "legal_reviewer", "brand_manager", "admin"]);
const REVIEWERS = new Set(["reviewer", ...APPROVERS]);

/** POST /api/reviews needs the `submit` permission (submitter, admin), confirmed live. */
export const canSubmit = (role: string) => role === "submitter" || role === "admin";
export const canApprove = (role: string) => APPROVERS.has(role);
export const canReview = (role: string) => REVIEWERS.has(role);
export const roleName = (role: string) => role.replace(/_/g, " ");

/** States a decision can be made from (approval_rules.DECIDABLE_STATES). */
export const isDecidable = (status: string) => status === "completed" || status === "needs_human_review";
