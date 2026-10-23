/**
 * Intent-lock: phrases the writer marked as must-keep (price, date, product name). Kept per review
 * in this browser only; the backend has no field for them yet.
 */
const key = (reviewId: string) => `audit-ai.additions.locks.${reviewId}`;

export function loadLocks(reviewId: string): string[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(key(reviewId)) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}
export function saveLocks(reviewId: string, locks: string[]) {
  try {
    window.localStorage.setItem(key(reviewId), JSON.stringify(locks));
  } catch {
    /* storage blocked: locks last for this page only */
  }
}

/** Locked phrases a suggestion would remove: present in the flagged text, missing from the fix. */
export const brokenBy = (original: string, suggestion: string, locks: string[]) =>
  locks.filter((l) => original.includes(l) && !suggestion.includes(l));

/** Locked phrases no longer present in the draft. */
export const missingIn = (draft: string, locks: string[]) => locks.filter((l) => !draft.includes(l));
