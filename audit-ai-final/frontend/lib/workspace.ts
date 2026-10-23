"use client";

/**
 * Small per-browser workspace memory (localStorage; every access guarded, storage can be blocked).
 *
 * - The active brand lives in lib/brand.ts (picked from GET /api/brands, never typed).
 * - Review text: kept as a fallback for older backends; ReviewOut.text from the API wins.
 */
const TEXT_KEY = (reviewId: string) => `audit-ai.review-text.${reviewId}`;
const TEXT_INDEX = "audit-ai.review-text-index";
const KEEP = 20;

function get(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function set(key: string, value: string | null) {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    /* storage blocked or full: the feature degrades, nothing breaks */
  }
}


export const getReviewText = (reviewId: string) => get(TEXT_KEY(reviewId));
export function rememberReviewText(reviewId: string, text: string) {
  set(TEXT_KEY(reviewId), text);
  let ids: string[] = [];
  try {
    ids = JSON.parse(get(TEXT_INDEX) ?? "[]");
  } catch {
    /* corrupt index: start again */
  }
  ids = [reviewId, ...ids.filter((x) => x !== reviewId)];
  for (const old of ids.slice(KEEP)) set(TEXT_KEY(old), null);
  set(TEXT_INDEX, JSON.stringify(ids.slice(0, KEEP)));
}

/* ---- The review the Decide and Record stages work on, and decisions made in this browser ----
   The stage bar links carry no id, so Decide/Record fall back to the last review opened.
   GET /api/reviews/{id} returns the decision OUTCOME (review.status) but not its note or time,
   and the history route needs a content_item_id nothing returns, so the decision event from
   the approve/request-changes response is kept here too. */
const LAST_REVIEW = "audit-ai.last-review";
const DECISION_KEY = (reviewId: string) => `audit-ai.decision.${reviewId}`;

export const getLastReviewId = () => get(LAST_REVIEW);
export const setLastReviewId = (id: string) => set(LAST_REVIEW, id);

export type SavedDecision = { action: string; note: string | null; created_at: string; actor_user_id: string; version_number: number | null };
export function getDecision(reviewId: string): SavedDecision | null {
  try {
    return JSON.parse(get(DECISION_KEY(reviewId)) ?? "null");
  } catch {
    return null;
  }
}
export const saveDecision = (reviewId: string, d: SavedDecision) => set(DECISION_KEY(reviewId), JSON.stringify(d));
