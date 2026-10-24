import type { FindingOut, ReviewOut } from "@/lib/api/types";

/** Plain-language labels for backend status strings. Unknown values fall back to a readable form. */
const human = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Verdict chip: glyph + word (never colour alone). Unverified is never shown as false. */
export function verdict(status: FindingOut["verification_status"]) {
  switch (status) {
    case "supported":
      return { glyph: "✓", label: "Matches", tone: "supported" };
    case "contradicted":
      return { glyph: "≠", label: "Doesn’t match", tone: "contradicted" };
    case "unverified":
      return { glyph: "?", label: "Not proven yet", tone: "unverified" };
    case "conflicting_sources":
      return { glyph: "⇄", label: "Approved documents disagree, check which is correct", tone: "unverified" };
    case "not_applicable":
      // Not a claim verdict (rule findings carry this; see findingChip for how they are shown).
      return { glyph: "–", label: "No claim verdict", tone: "neutral" };
    default:
      return { glyph: "?", label: human(status), tone: "unverified" };
  }
}

const SEVERITY: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };
export function severity(s: FindingOut["severity"]) {
  const n = SEVERITY[s] ?? 0;
  return { marks: "●".repeat(n) + "○".repeat(4 - n), word: human(s) };
}

/* ---- Brand-rule findings (check_type "rule"): not claim verdicts ---- */

export const isRule = (f: FindingOut) => f.check_type === "rule";
/** "document" scope: something is missing from the whole draft (the span just anchors on line 1). */
export const isWholeDraft = (f: FindingOut) => isRule(f) && f.scope === "document";

const RULE_CATEGORY: Record<string, string> = {
  terminology: "Terminology",
  brand_compliance: "Brand compliance",
  accessibility: "Accessibility",
};
export const ruleCategoryLabel = (c: string | null | undefined) => (c ? (RULE_CATEGORY[c] ?? human(c)) : "Brand rule");

const RULE_TYPE: Record<string, string> = {
  required_term: "Required term",
  prohibited_term: "Prohibited term",
  product_naming: "Product name",
  preferred_term: "Preferred term",
  spelling: "Spelling",
  terminology_consistency: "Consistent wording",
  required_disclaimer: "Required disclaimer",
  numeric_limit: "Number limit",
  all_caps_run: "All capitals",
  emoji_run: "Emoji runs",
  vague_link_text: "Vague link text",
  missing_alt_text: "Image alt text",
  heading_structure: "Heading order",
  missing_captions: "Media captions",
  low_contrast: "Colour contrast",
};
export const ruleTypeLabel = (t: string | null | undefined) => (t ? (RULE_TYPE[t] ?? human(t)) : "Rule");

/** Chip for any finding: rule findings get a "§ <category> rule" chip, never a claim verdict. */
export function findingChip(f: FindingOut) {
  if (isRule(f)) return { glyph: "§", label: `${ruleCategoryLabel(f.category)} rule`, tone: "rule" };
  return verdict(f.verification_status);
}

/** Label for a suggestion, by where it comes from. */
export const suggestionLabel = (f: FindingOut) =>
  f.suggestion_basis === "brand_rule" ? "From brand rules" : f.suggestion_basis === "approved_document" ? "From approved document" : "We suggest";

/**
 * The one suggestion to offer for a finding, with an honest label. Nothing is ever applied
 * automatically; this only decides what to show.
 * - rule findings: suggested_correction, labelled by suggestion_basis;
 * - unverified claims: safer_wording ("Safer wording, not evidence-backed"). Older backends put that
 *   softened text in suggested_correction instead, so it gets the same label there;
 * - other claims (contradicted): suggested_correction, backed by the cited quote.
 */
export const SAFER_WORDING_LABEL = "Safer wording, not evidence-backed";
export function suggestionFor(f: FindingOut): { text: string; label: string; evidenceBacked: boolean } | null {
  if (isRule(f)) return f.suggested_correction ? { text: f.suggested_correction, label: suggestionLabel(f), evidenceBacked: f.suggestion_basis === "approved_document" } : null;
  if (f.verification_status === "unverified") {
    const text = f.safer_wording ?? f.suggested_correction;
    return text ? { text, label: SAFER_WORDING_LABEL, evidenceBacked: false } : null;
  }
  return f.suggested_correction ? { text: f.suggested_correction, label: "We suggest (backed by your documents)", evidenceBacked: true } : null;
}

/** Rule checks status for the review. Only "complete" (or no rules at all on old reviews) may look rule-clean. */
export const rulesUnfinished = (r: ReviewOut) => r.rules_status === "incomplete" || r.rules_status === "not_applied";

/** Headline for the whole review. `completed` never means approved. */
export function reviewHeadline(r: ReviewOut, stub: boolean) {
  if (stub) return "Placeholder result";
  switch (r.status) {
    case "completed":
      if (rulesUnfinished(r)) return "Claims matched · rules not fully checked";
      return r.findings.length ? "Everything matched" : "Nothing to check";
    case "needs_human_review": {
      const n = r.findings.filter((f) => f.verification_status !== "supported").length;
      return n === 1 ? "1 thing to look at" : `${n} things to look at`;
    }
    case "failed":
      return "Couldn’t check this";
    default:
      return human(r.status);
  }
}

export const isStub = (f: FindingOut) => f.category === "stub";

/** Placeholder review: the stub finding, or the engine itself reporting a stub provider
 * (live backend sends engine.provider "stub-unconfigured" when no AI service is set up). */
export const isStubReview = (r: ReviewOut) => r.findings.some(isStub) || /^stub/i.test(r.engine?.provider ?? "");

/** Text after the "[STUB OUTPUT]" marker, for showing the server's own reason. */
export const stubReason = (f: FindingOut) => (f.explanation ?? "").replace(/^\[STUB OUTPUT\]\s*/, "");

export const checkName = (f: FindingOut) =>
  isRule(f)
    ? `${ruleCategoryLabel(f.category)} · ${ruleTypeLabel(f.rule_type)}`
    : f.category
      ? human(f.category)
      : f.check_type === "retrieval"
        ? "Facts"
        : human(f.check_type);
