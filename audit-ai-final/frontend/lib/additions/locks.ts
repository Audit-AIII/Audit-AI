/**
 * Intent-lock helpers. The locks themselves live on the server (GET / PUT
 * /api/content-versions/{id}/locks; the review carries `locked_phrases`), which never stores or offers
 * a suggestion that would break one. These pure checks are advisory only, for the user's OWN edits,
 * which the server does not block. Same rule as the engine (inkloom_verify.intent_lock): exact,
 * case-sensitive, and a phrase that occurs n times must still occur n times.
 */
const count = (text: string, phrase: string) => {
  if (!phrase) return 0;
  let n = 0;
  for (let at = text.indexOf(phrase); at >= 0; at = text.indexOf(phrase, at + phrase.length)) n++;
  return n;
};

/** Locked phrases a suggestion would remove: it keeps fewer copies than the flagged text has. */
export const brokenBy = (original: string, suggestion: string, locks: string[]) => locks.filter((l) => count(suggestion, l) < count(original, l));

/** Locked phrases the draft keeps fewer times than the checked text, or not at all (a lock marked on
 * newly typed words still has to be there once). */
export const missingIn = (checked: string, draft: string, locks: string[]) => locks.filter((l) => count(draft, l) < Math.max(1, count(checked, l)));
