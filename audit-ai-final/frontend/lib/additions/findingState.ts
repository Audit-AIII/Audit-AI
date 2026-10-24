/**
 * Per-finding Dismiss / comments, applied from the backend's responses only (never optimistic).
 * Pure (type imports only), so qa/unit can load it under plain Node.
 * Dismissed is not "supported": nothing here touches verification_status, evidence or suggestions.
 */
import type { FindingComment, FindingDecision, FindingOut, ReviewOut } from "../api/types";

export const DISMISSED = { glyph: "⊖", label: "Dismissed" } as const;
/** findings.py: DecisionBody.note and CommentBody.body, max_length=2000 (Python counts code points). */
export const TEXT_MAX = 2000;

export const isDismissed = (f: FindingOut) => !!f.dismissal;

/** The review with one finding's `dismissal` set from a 201 dismiss / restore response. */
export function applyDecision(review: ReviewOut, d: FindingDecision): ReviewOut {
  return {
    ...review,
    findings: review.findings.map((f) =>
      f.finding_id !== d.finding_id
        ? f
        : { ...f, dismissal: d.action === "dismissed" ? { by_user_id: d.actor_user_id, at: d.created_at, note: d.note } : null },
    ),
  };
}

/** The review with comment_count raised by one for a 201 comment. */
export function applyComment(review: ReviewOut, c: FindingComment): ReviewOut {
  return {
    ...review,
    findings: review.findings.map((f) => (f.finding_id === c.finding_id ? { ...f, comment_count: (f.comment_count ?? 0) + 1 } : f)),
  };
}

/** "2 open, 1 dismissed": dismissed findings are counted, never hidden. */
export function openDismissed(findings: FindingOut[]) {
  const dismissed = findings.filter(isDismissed).length;
  return { open: findings.length - dismissed, dismissed };
}

export const codePoints = (s: string) => Array.from(s).length;

/** Why a comment can't be sent yet (mirrors CommentBody: 1-2000 characters, not blank), or null. */
export function commentProblem(body: string): string | null {
  if (!body.trim()) return "Write something first.";
  if (codePoints(body) > TEXT_MAX) return `At most ${TEXT_MAX} characters.`;
  return null;
}

/** Same limit for the optional dismiss note; empty is fine. */
export const noteProblem = (note: string) => (codePoints(note) > TEXT_MAX ? `At most ${TEXT_MAX} characters.` : null);

export const commentCountText = (n: number) => (n === 1 ? "1 comment" : `${n} comments`);
