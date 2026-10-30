"use client";

import { isRule, isStub, verdict } from "@/components/app/reviewLabels";
import { countText, isStyleRule, toneCount } from "@/lib/additions/summary";
import { DISMISSED, isDismissed } from "@/lib/additions/findingState";
import { isTone } from "@/lib/additions/tone";
import type { FindingOut, SummaryCounts } from "@/lib/api/types";

/** Fixed columns, worst first (same glyphs and words as the finding chips). `api`: its key in summary_counts. */
const CELLS: { key: string; api?: keyof SummaryCounts; glyph: string; label: string; tone: string }[] = [
  { key: "contradicted", api: "contradicted", ...verdict("contradicted") },
  { key: "conflicting_sources", api: "conflicting", glyph: "⇄", label: "Documents disagree", tone: "unverified" },
  { key: "unverified", api: "unverified", ...verdict("unverified") },
  { key: "rule", glyph: "§", label: "Brand rule", tone: "rule" },
  { key: "supported", api: "supported", ...verdict("supported") },
];
const cellKey = (f: FindingOut) => (isRule(f) ? "rule" : isTone(f) ? "tone" : f.verification_status);

/**
 * What the checker found, at a glance. Numbers come from the server's summary_counts, and a missing
 * count shows "–", never 0. summary_counts has no brand-rule count, so that cell counts the findings
 * the server sent. Cells stay when empty (dimmed), so the layout never shifts; a cell jumps to the
 * first finding of its kind. Dismissed findings stay counted in their kind, as on the server.
 */
export function ReviewSummary({
  findings,
  counts,
  current,
  onSelect,
}: {
  findings: FindingOut[];
  counts?: SummaryCounts | null;
  current?: string;
  onSelect: (id: string) => void;
}) {
  const real = findings.filter((f) => !isStub(f));
  const dismissed = real.filter(isDismissed).length;
  const style = toneCount(counts);
  const firstStyle = real.find(isStyleRule);
  const voice = real.filter(isTone);
  return (
    <section className="tally add-summary card" aria-label="What the checker found">
      <div className="tally__total">
        <span className="tally__count">{real.length}</span>
        <span className="t-caption">{real.length === 1 ? "finding" : "findings"}</span>
        <span className="tally__note">
          <span aria-hidden="true">●</span> {countText(counts?.needs_human_review)} {counts?.needs_human_review === 1 ? "needs" : "need"} a person
        </span>
        {style > 0 && (
          <button type="button" className="add-summary__style" onClick={() => firstStyle && onSelect(firstStyle.finding_id)} disabled={!firstStyle}>
            <span aria-hidden="true">§</span> {style} style {style === 1 ? "rule" : "rules"} (capitals, emoji)
          </button>
        )}
        {/* Real brand voice findings, kept apart from the two style rules the API counts as "tone". */}
        {voice.length > 0 && (
          <button type="button" className="add-summary__style" onClick={() => onSelect(voice[0].finding_id)}>
            <span aria-hidden="true">¶</span> {voice.length} brand voice {voice.length === 1 ? "finding" : "findings"}
          </button>
        )}
        {dismissed > 0 && (
          <span className="tally__note">
            <span aria-hidden="true">{DISMISSED.glyph}</span> {dismissed} dismissed
          </span>
        )}
      </div>
      <ul className="tally__list">
        {CELLS.map((k) => {
          const items = real.filter((f) => cellKey(f) === k.key);
          const on = items.some((f) => f.finding_id === current);
          const count = k.api ? countText(counts?.[k.api]) : String(items.length);
          return (
            <li key={k.key}>
              <button
                type="button"
                className={`tally__cell${on ? " is-on" : ""}`}
                onClick={() => items[0] && onSelect(items[0].finding_id)}
                disabled={items.length === 0}
                aria-pressed={on}
              >
                <span className="tally__count">{count}</span>
                <span className={`chip chip--${k.tone}`}>
                  {k.glyph} {k.label}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
