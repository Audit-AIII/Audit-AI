/**
 * Dashboard counts, computed only from the reviews GET /api/reviews returned (no estimates, no
 * sample data). Pure (type imports only) so qa/unit can load it under plain Node.
 */
import type { FindingOut, ReviewOut } from "../api/types";

/** Where each draft stands, in a fixed order (zero rows stay, so the panel never reshuffles). */
export const STATUS_GROUPS: { key: string; label: string; glyph: string; tone: string; statuses: string[] }[] = [
  { key: "waiting", label: "Waiting for your decision", glyph: "●", tone: "warn", statuses: ["needs_human_review"] },
  { key: "clean", label: "Checked, nothing flagged", glyph: "○", tone: "none", statuses: ["completed"] },
  { key: "approved", label: "Approved", glyph: "✓", tone: "ok", statuses: ["approved"] },
  { key: "sent_back", label: "Sent back or rejected", glyph: "↩", tone: "none", statuses: ["changes_requested", "rejected"] },
  { key: "recheck", label: "Source changed, re-check", glyph: "↻", tone: "warn", statuses: ["source_changed"] },
  { key: "failed", label: "Check didn’t run", glyph: "!", tone: "bad", statuses: ["failed"] },
  { key: "running", label: "Still being checked", glyph: "…", tone: "none", statuses: ["draft", "queued", "analysing"] },
];

export function statusCounts(reviews: ReviewOut[]) {
  return STATUS_GROUPS.map((g) => ({ ...g, count: reviews.filter((r) => g.statuses.includes(r.status)).length }));
}

const isStub = (f: FindingOut) => f.category === "stub";
/** What the checker said across every real finding (placeholders left out), worst first. */
export const VERDICT_KINDS = ["contradicted", "conflicting_sources", "unverified", "rule", "supported"] as const;
export type VerdictKind = (typeof VERDICT_KINDS)[number];

export function verdictMix(reviews: ReviewOut[]): Record<VerdictKind, number> {
  const out: Record<VerdictKind, number> = { contradicted: 0, conflicting_sources: 0, unverified: 0, rule: 0, supported: 0 };
  for (const r of reviews)
    for (const f of r.findings) {
      if (isStub(f)) continue;
      const k = (f.check_type === "rule" ? "rule" : f.verification_status) as VerdictKind;
      if (k in out) out[k] += 1;
    }
  return out;
}

/** Reviews whose result is the no-provider placeholder (shown as a caveat, never as a result). */
export const placeholderCount = (reviews: ReviewOut[]) => reviews.filter((r) => r.findings.some(isStub)).length;

const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

/** Reviews started per local calendar day, for the last `days` days ending today (oldest first). */
export function lastDays(reviews: ReviewOut[], days = 7, now = new Date()) {
  const out: { key: string; label: string; count: number }[] = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    out.push({ key: dayKey(d), label: i === 0 ? "Today" : d.toLocaleDateString("en-GB", { weekday: "short" }), count: 0 });
  }
  for (const r of reviews) {
    const slot = out.find((o) => o.key === dayKey(new Date(r.created_at)));
    if (slot) slot.count += 1;
  }
  return out;
}
