import type { FindingOut } from "../api/types";

/**
 * Evidence coverage from real findings only. The text is split into sentences; each sentence takes
 * the most serious verdict of the findings that overlap it (contradicted > unverified/conflicting >
 * supported), or "none" when no finding touches it (no claim checked there).
 * Coverage % = supported claim sentences / all claim sentences. No claims -> null (never 0% or 100%).
 */
/** Code-point span -> UTF-16 indices (same as lib/text/codepoints.ts; inlined so this file has no
 * runtime imports and its unit test runs under plain Node). */
function spanToUtf16(text: string, span: { start: number; end: number }) {
  const at = (cp: number) => {
    let units = 0;
    let seen = 0;
    for (const ch of text) {
      if (seen >= cp) break;
      units += ch.length;
      seen++;
    }
    return units;
  };
  return { start: at(Math.max(0, span.start)), end: at(Math.max(span.start, span.end)) };
}

export type SentenceStatus = "supported" | "unverified" | "contradicted" | "none";
export type Sentence = { text: string; start: number; end: number; status: SentenceStatus; findings: FindingOut[] };

const RANK: Record<string, number> = { contradicted: 3, conflicting_sources: 2, unverified: 2, supported: 1 };
const asStatus = (s: string): SentenceStatus => (s === "contradicted" ? "contradicted" : s === "supported" ? "supported" : "unverified");

export function splitSentences(text: string): { text: string; start: number; end: number }[] {
  const out: { text: string; start: number; end: number }[] = [];
  const Seg = (Intl as unknown as { Segmenter?: new (l?: string, o?: { granularity: string }) => { segment(s: string): Iterable<{ segment: string; index: number }> } }).Segmenter;
  if (Seg) {
    for (const s of new Seg(undefined, { granularity: "sentence" }).segment(text)) out.push({ text: s.segment, start: s.index, end: s.index + s.segment.length });
  } else {
    const re = /[^.!?\n]+[.!?]*\s*|\n+/g;
    for (let m = re.exec(text); m; m = re.exec(text)) out.push({ text: m[0], start: m.index, end: m.index + m[0].length });
  }
  return out.filter((s) => s.text.trim());
}

export function coverage(text: string, findings: FindingOut[]) {
  const ranged = findings
    .filter((f) => f.verification_status !== "not_applicable")
    .map((f) => ({ f, ...spanToUtf16(text, f.span) }));
  const sentences: Sentence[] = splitSentences(text).map((s) => {
    const hits = ranged.filter((r) => r.start < s.end && r.end > s.start).map((r) => r.f);
    const top = hits.reduce<FindingOut | null>((a, f) => (!a || (RANK[f.verification_status] ?? 0) > (RANK[a.verification_status] ?? 0) ? f : a), null);
    return { ...s, status: top ? asStatus(top.verification_status) : "none", findings: hits };
  });
  const claims = sentences.filter((s) => s.status !== "none");
  const count = (st: SentenceStatus) => sentences.filter((s) => s.status === st).length;
  return {
    sentences,
    counts: { supported: count("supported"), unverified: count("unverified"), contradicted: count("contradicted"), none: count("none") },
    percent: claims.length ? Math.round((count("supported") / claims.length) * 100) : null,
  };
}
