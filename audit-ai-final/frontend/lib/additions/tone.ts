import type { FindingOut, ReviewOut } from "../api/types";

/**
 * Brand voice findings (check_type "tone"). No checker sends these yet, and the fields come from a
 * draft proposal (docs/round3/handoff-tone.md), so everything here only ever reads what the API sent;
 * it never creates a finding. Pure, so qa/unit can test it.
 *
 * A brand voice judgement must prove itself like any other claim: it needs the guideline passage it
 * relies on, and the server's check of that passage. Anything else stays off the page.
 * "omit" hides failed ones; "uncertain" shows those that cite a passage as dashed "Uncertain" cards.
 */
export const TONE_UNCERTAIN_MODE: "omit" | "uncertain" = "omit";

export const isTone = (f: Pick<FindingOut, "check_type">) => f.check_type === "tone";
const hasPassage = (f: FindingOut) => !!f.guideline_quote?.trim();
/** Cited a passage but didn't pass the server's check: never highlighted in the draft. */
export const isUncertainTone = (f: FindingOut) => isTone(f) && hasPassage(f) && f.validation_status !== "validated";

export function splitTone(findings: FindingOut[], mode: "omit" | "uncertain" = TONE_UNCERTAIN_MODE) {
  const shown: FindingOut[] = [];
  let hidden = 0;
  for (const f of findings) {
    const keep = !isTone(f) || (hasPassage(f) && (f.validation_status === "validated" || mode === "uncertain"));
    if (keep) shown.push(f);
    else hidden++;
  }
  return { shown, hidden };
}

/** The review every page reads: unproven brand voice findings are gone, and counted. */
export function withToneRule(review: ReviewOut): ReviewOut {
  const { shown, hidden } = splitTone(review.findings);
  return hidden === 0 ? review : { ...review, findings: shown, hidden_tone_count: hidden };
}

export const hiddenToneText = (n: number) =>
  `${n} brand voice ${n === 1 ? "observation" : "observations"} hidden because ${n === 1 ? "it cites" : "they cite"} no valid guideline passage.`;
