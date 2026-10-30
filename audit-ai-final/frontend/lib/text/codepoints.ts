/**
 * The backend's finding spans are Unicode CODE POINT offsets (contract/README.md, "Offsets").
 * JavaScript strings index UTF-16 units, so an emoji or other non-BMP character counts as 2.
 * Never slice `text` with a span directly: convert first.
 */

/** Code point offset → UTF-16 index into `text`. Offsets past the end clamp to text.length. */
export function cpToUtf16(text: string, cp: number): number {
  let units = 0;
  let seen = 0;
  for (const ch of text) {
    if (seen >= cp) break;
    units += ch.length; // 1 for BMP, 2 for a surrogate pair
    seen++;
  }
  return units;
}

/** Converts a code-point span to UTF-16 indices that `text.slice` understands. */
export function spanToUtf16(text: string, span: { start: number; end: number }) {
  const start = cpToUtf16(text, Math.max(0, span.start));
  const end = cpToUtf16(text, Math.max(span.start, span.end));
  return { start, end };
}

/**
 * Does the span really hold this finding's words? Whitespace is compared loosely, because extracted
 * text can reflow; anything else means highlighting it would mark the wrong words.
 */
export function spanLocated(text: string, span: { start: number; end: number }, original: string) {
  const { start, end } = spanToUtf16(text, span);
  const squash = (s: string) => s.replace(/\s+/g, " ").trim();
  return squash(text.slice(start, end)) === squash(original);
}

export type Segment<T> = { text: string; marks: T[] };

/**
 * Splits `text` into runs for highlighting. Each run lists every item whose span covers it, so
 * overlapping findings are kept (the caller decides how to show a run with 2+ marks).
 */
export function segment<T>(text: string, items: { span: { start: number; end: number }; item: T }[]): Segment<T>[] {
  const ranges = items
    .map(({ span, item }) => ({ ...spanToUtf16(text, span), item }))
    .filter((r) => r.end > r.start);
  const cuts = new Set<number>([0, text.length]);
  for (const r of ranges) {
    cuts.add(r.start);
    cuts.add(r.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const out: Segment<T>[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [a, b] = [points[i], points[i + 1]];
    out.push({ text: text.slice(a, b), marks: ranges.filter((r) => r.start <= a && r.end >= b).map((r) => r.item) });
  }
  return out;
}
