// node --experimental-strip-types qa/unit/finding-state.test.mts
// Fixtures: services/api/API.md (Review shape, Kora X2 example) and
// services/api/tests/test_intent_lock_dismiss_comments.py (note, comment bodies, invalid bodies).
import assert from "node:assert/strict";
import { applyComment, applyDecision, commentCountText, commentProblem, isDismissed, noteProblem, openDismissed } from "../../lib/additions/findingState.ts";

const finding = (id: string, original_text: string, verification_status: string) =>
  ({ finding_id: id, original_text, verification_status, evidence: [], suggested_correction: null, dismissal: null, comment_count: 0 }) as never;
const review = {
  id: "r",
  findings: [finding("a", "The Kora X2 is India's number one smartphone.", "unverified"), finding("b", "It packs a 6,000 mAh battery.", "contradicted")],
} as never as Parameters<typeof applyDecision>[0];

// dismiss: only `dismissal` changes, the verdict stays (dismissed is not "supported")
const dismissed = applyDecision(review, { id: "d1", finding_id: "b", action: "dismissed", note: "we say 24h in the US ad", actor_user_id: "u", created_at: "2026-10-24T10:00:00Z" });
const b = dismissed.findings[1];
assert.deepEqual(b.dismissal, { by_user_id: "u", at: "2026-10-24T10:00:00Z", note: "we say 24h in the US ad" });
assert.equal(b.verification_status, "contradicted");
assert.equal(isDismissed(dismissed.findings[0]), false, "other findings untouched");
assert.deepEqual(openDismissed(dismissed.findings), { open: 1, dismissed: 1 });
assert.equal(dismissed.findings.length, 2, "never hidden");
// restore clears it
const restored = applyDecision(dismissed, { id: "d2", finding_id: "b", action: "restored", note: null, actor_user_id: "u", created_at: "2026-10-24T10:01:00Z" });
assert.equal(restored.findings[1].dismissal, null);
assert.deepEqual(openDismissed(restored.findings), { open: 2, dismissed: 0 });
assert.equal(review.findings[1].dismissal, null, "input not mutated");

// comments: 1-2000 characters, not blank (CommentBody)
for (const ok of ["Check with legal.", "Legal says fine.", "x".repeat(2000), "₹".repeat(2000)]) assert.equal(commentProblem(ok), null, ok.slice(0, 20));
for (const bad of ["", "   ", "x".repeat(2001)]) assert.notEqual(commentProblem(bad), null, bad.slice(0, 20));
assert.equal(commentProblem("🎧".repeat(2000)), null, "counted in code points like the backend, not UTF-16 units");
assert.equal(noteProblem(""), null, "the dismiss note is optional");
assert.notEqual(noteProblem("x".repeat(2001)), null);
const commented = applyComment(applyComment(review, { id: "c1", finding_id: "a", author_user_id: "u", body: "Check with legal.", created_at: "t" }),
  { id: "c2", finding_id: "a", author_user_id: "u", body: "Legal says fine.", created_at: "t" });
assert.equal(commented.findings[0].comment_count, 2);
assert.equal(commentCountText(1), "1 comment");
assert.equal(commentCountText(2), "2 comments");
console.log("finding state: all assertions passed");
