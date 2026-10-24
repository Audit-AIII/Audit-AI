import { findingChip, isRule } from "@/components/app/reviewLabels";
import type { FindingOut } from "@/lib/api/types";

/** Glyph + word + relief for each state (DESIGN §16). Unverified is never shown as false. */
const VERDICT: Record<string, { glyph: string; label: string; tone: string }> = {
  supported: { glyph: "✓", label: "Supported", tone: "ok" },
  contradicted: { glyph: "≠", label: "Contradicted", tone: "bad" },
  unverified: { glyph: "?", label: "Not proven yet", tone: "warn" },
  conflicting_sources: { glyph: "⇄", label: "Approved documents disagree, check which is correct", tone: "warn" },
  not_applicable: { glyph: "–", label: "No claim", tone: "none" },
};
export const verdictOf = (s: string) => VERDICT[s] ?? { glyph: "?", label: s.replace(/_/g, " "), tone: "warn" };

export function StatusBadge({ status }: { status: FindingOut["verification_status"] | "none" }) {
  const v = status === "none" ? VERDICT.not_applicable : verdictOf(status);
  return (
    <span className={`add-badge add-badge--${v.tone}`}>
      <span aria-hidden="true">{v.glyph}</span> {v.label}
    </span>
  );
}

/** Badge for a whole finding: brand-rule findings show "§ <category> rule", claims their verdict. */
export function FindingBadge({ f }: { f: FindingOut }) {
  if (isRule(f)) {
    const c = findingChip(f);
    return (
      <span className="add-badge add-badge--rule">
        <span aria-hidden="true">{c.glyph}</span> {c.label}
      </span>
    );
  }
  return <StatusBadge status={f.verification_status} />;
}

const SOURCE: Record<string, { glyph: string; label: string; tone: string }> = {
  approved: { glyph: "✓", label: "Approved", tone: "ok" },
  draft: { glyph: "…", label: "Draft", tone: "warn" },
  superseded: { glyph: "↺", label: "Replaced", tone: "none" },
  archived: { glyph: "–", label: "Withdrawn", tone: "none" },
};
export function SourceStatusBadge({ status }: { status: string }) {
  const s = SOURCE[status] ?? { glyph: "?", label: status, tone: "none" };
  return (
    <span className={`add-badge add-badge--${s.tone}`}>
      <span aria-hidden="true">{s.glyph}</span> {s.label}
    </span>
  );
}

const LEVEL: Record<string, number> = { low: 1, medium: 2, high: 3, critical: 4 };
export function SeverityBadge({ severity }: { severity: string }) {
  const n = LEVEL[severity] ?? 0;
  return (
    <span className="add-sev" aria-label={`${severity} severity`}>
      <span aria-hidden="true">{"●".repeat(n)}{"○".repeat(4 - n)}</span> {severity.replace(/^\w/, (c) => c.toUpperCase())}
    </span>
  );
}
