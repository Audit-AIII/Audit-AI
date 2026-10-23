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
      return { glyph: "⇄", label: "Your documents disagree", tone: "unverified" };
    case "not_applicable":
      return { glyph: "–", label: "Not checked", tone: "neutral" };
    default:
      return { glyph: "?", label: human(status), tone: "unverified" };
  }
}

const SEVERITY: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };
export function severity(s: FindingOut["severity"]) {
  const n = SEVERITY[s] ?? 0;
  return { marks: "●".repeat(n) + "○".repeat(4 - n), word: human(s) };
}

/** Headline for the whole review. `completed` never means approved. */
export function reviewHeadline(r: ReviewOut, stub: boolean) {
  if (stub) return "Placeholder result";
  switch (r.status) {
    case "completed":
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
  f.category ? human(f.category) : f.check_type === "retrieval" ? "Facts" : human(f.check_type);
