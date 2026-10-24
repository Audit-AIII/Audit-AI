/**
 * Single-user accounts (DECISIONS.md, decision 1): the signed-in owner can do everything in their
 * own account, so no button is hidden or disabled because of a role. The server still refuses for
 * other reasons (a stale version, a cited source that changed) and the UI shows its message.
 * Kept as functions so call sites stay readable if roles return later.
 */
export const canSubmit = () => true;
export const canManageSources = () => true;
export const canApprove = () => true;
export const canReview = () => true;
export const roleName = (role: string) => role.replace(/_/g, " ");

/** States a decision can be made from (approval_rules.DECIDABLE_STATES). */
export const isDecidable = (status: string) => status === "completed" || status === "needs_human_review";
