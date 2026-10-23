"use client";

/**
 * Small per-browser workspace memory (localStorage; every access guarded, storage can be blocked).
 *
 * - Brand ID: the backend has no "list my brands" route yet, so the brand to review against is
 *   entered once on the Sources stage (the seed script prints it as BRAND_ID).
 * - Review text: GET /api/reviews/{id} does not return the submitted text, only each finding's
 *   own `original_text`. We keep the text we sent, keyed by review id, so highlighting still
 *   works after a refresh in this browser.
 */
const BRAND_KEY = "audit-ai.brand-id";
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

export const getBrandId = () => get(BRAND_KEY) ?? "";
export const setBrandId = (id: string) => set(BRAND_KEY, id.trim() || null);

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
