/**
 * The backend's stored evaluation run: EvaluationOut / PerCheckOut / SplitOut / RatioOut, copied
 * field by field from services/api/src/inkloom_api/routers/evaluations.py (GET /api/evaluations/latest,
 * POST /api/evaluations). No runtime imports, so the unit test can load it under plain Node.
 * Nothing here invents or defaults a number: a field of the wrong type rejects the whole response.
 */
export type Ratio = { numerator: number; denominator: number; value: number | null };
export type PerCheck = {
  check: string;
  catch_rate: number | null;
  false_positive_rate: number | null;
  n: number;
  /** Missing or null on runs stored before these were recorded. */
  catch_rate_ratio?: Ratio | null;
  false_positive_rate_ratio?: Ratio | null;
};
export type Split = { n: number; catch_rate: Ratio; false_positive_rate: Ratio };
export type RunEvaluation = {
  catch_rate: number | null;
  false_positive_rate: number | null;
  per_check: PerCheck[];
  sample_size: number;
  run_at: string;
  id: string;
  status: string;
  engine_prompt_version: string | null;
  dataset_version: string;
  limits_note: string;
  latency_ms_p50: number | null;
  provider_failure_rate: number | null;
  coverage: string;
  /** null for runs stored before per-split metrics existed */
  by_split: Record<string, Split> | null;
  /** "live" | "scripted" | "mixed" | null (no model answered) */
  provider_mode: string | null;
  /** Counts behind the two combined rates; missing on an older backend. */
  catch_rate_ratio?: Ratio | null;
  false_positive_rate_ratio?: Ratio | null;
  /** The held-out split, the figure to quote. Null when a run has none. */
  headline?: { split: string; n: number; catch_rate: Ratio; false_positive_rate: Ratio } | null;
};

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);
const numOrNull = (x: unknown) => x === null || isNum(x);
const strOrNull = (x: unknown) => x === null || typeof x === "string";

function badRatio(r: unknown): boolean {
  return !isObj(r) || !isNum(r.numerator) || !isNum(r.denominator) || !numOrNull(r.value);
}

/** Why the response doesn't match EvaluationOut, or null when it does. */
export function runEvaluationProblem(x: unknown): string | null {
  if (!isObj(x)) return "not an object";
  for (const k of ["catch_rate", "false_positive_rate", "latency_ms_p50", "provider_failure_rate"]) if (!numOrNull(x[k])) return `${k} must be a number or null`;
  if (!Array.isArray(x.per_check)) return "per_check must be a list";
  for (const [i, c] of x.per_check.entries()) {
    if (!isObj(c) || typeof c.check !== "string" || !numOrNull(c.catch_rate) || !numOrNull(c.false_positive_rate) || !isNum(c.n)) return `per_check[${i}] is malformed`;
  }
  if (!isNum(x.sample_size)) return "sample_size must be a number";
  for (const k of ["run_at", "id", "status", "dataset_version", "limits_note", "coverage"]) if (typeof x[k] !== "string") return `${k} must be text`;
  for (const k of ["engine_prompt_version", "provider_mode"]) if (!strOrNull(x[k])) return `${k} must be text or null`;
  if (x.by_split !== null) {
    if (!isObj(x.by_split)) return "by_split must be an object or null";
    for (const [name, s] of Object.entries(x.by_split)) {
      if (!isObj(s) || !isNum(s.n) || badRatio(s.catch_rate) || badRatio(s.false_positive_rate)) return `by_split.${name} is malformed`;
    }
  }
  for (const k of ["catch_rate_ratio", "false_positive_rate_ratio"]) if (x[k] != null && badRatio(x[k])) return `${k} is malformed`;
  if (x.headline != null) {
    const h = x.headline;
    if (!isObj(h) || typeof h.split !== "string" || !isNum(h.n) || badRatio(h.catch_rate) || badRatio(h.false_positive_rate)) return "headline is malformed";
  }
  return null;
}

/** True for the new shape (has the EvaluationOut headline fields), as opposed to evaluation-summary-v1. */
export const looksLikeRunEvaluation = (x: unknown) => isObj(x) && "catch_rate" in x && "per_check" in x && x.contract === undefined;

/**
 * A rate as a percentage with the backend's precision: the fraction it sent, times 100, with no
 * extra rounding beyond trimming float noise (0.0364 -> "3.64%", 1.0 -> "100%"). null -> "–".
 */
export function formatRate(v: number | null): string {
  if (v === null) return "–";
  const pct = Math.round(v * 100 * 1e6) / 1e6;
  return `${pct}%`;
}

/** "18 of 18" for a ratio; "–" with "no cases" when the denominator is 0 (value null). */
export const formatRatio = (r: Ratio) => (r.denominator === 0 ? "no cases in this split" : `${r.numerator} of ${r.denominator}`);

/** Said instead of a number when nothing was measured. Never 0: a real 0 is a result. */
export const NOT_EVALUATED = "Not evaluated";

/** A rate, or null when nothing was measured: a null value, or a check that covered no claims. */
export const measured = (v: number | null, n?: number) => (v === null || n === 0 ? null : formatRate(v));

/**
 * "37 of 40 (92.5%)", with the counts first because they show how little one rate may rest on.
 * null when there were no cases (denominator 0), so it reads "Not evaluated", never 0%.
 */
export const ratioText = (r: Ratio) => (r.denominator === 0 || r.value === null ? null : `${r.numerator} of ${r.denominator} (${formatRate(r.value)})`);

/** Plain words for provider_mode, never colour alone. */
export function providerModeText(mode: string | null): { label: string; live: boolean } {
  if (mode === "live") return { label: "Live AI model", live: true };
  if (mode === "scripted") return { label: "Offline test run, not a real model.", live: false };
  if (mode === "mixed") return { label: "Mixed: partly a live model, partly the offline test model. Not a clean real-model run.", live: false };
  return { label: "No model answered during this run.", live: false };
}
