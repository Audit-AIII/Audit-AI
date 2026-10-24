"use client";

import { ApiError } from "@/lib/api/client";
import { isMissingRoute, request } from "./http";

/**
 * Insights + Trust Scorecard adapters.
 *   GET /api/analytics/brand-risk   (not on the backend yet: 404 -> { available: false })
 *   GET /api/evaluations/latest     (backend, any signed-in member): the latest evaluation report's
 *                                   summary, contract "evaluation-summary-v1", written by the engine's
 *                                   evaluation runner (services/verification/eval/run_eval.py).
 * The frontend computes no metric: it shows what the summary says, and refuses a response that does
 * not match the contract (schema: services/verification/schemas/evaluation_summary.schema.json).
 */
export type BrandRisk = {
  top_categories: { category: string; count: number }[];
  median_turnaround_minutes: number | null;
  re_review_rate: number | null;
  queue_age_minutes: { median: number | null; oldest: number | null };
  sample_size: number;
};
export type Maybe<T> = { available: true; data: T } | { available: false };

async function optional<T>(path: string, init?: Parameters<typeof request>[1]): Promise<Maybe<T>> {
  try {
    return { available: true, data: await request<T>(path, init) };
  } catch (err) {
    if (isMissingRoute(err)) return { available: false };
    throw err;
  }
}

export const brandRisk = (brandId: string) => optional<BrandRisk>(`/api/analytics/brand-risk?brand_id=${encodeURIComponent(brandId)}`);
/**
 * Two different 404s:
 *   - {"error": {"code": "NOT_FOUND", "message": "no evaluation has been run yet"}}: the route
 *     exists, nothing has been run -> an empty state (state "none"), not "needs backend";
 *   - FastAPI's default {"detail": "Not Found"} (no error body, so code BAD_RESPONSE): the route
 *     itself is missing -> { available: false }.
 */
export const isNoEvaluationYet = (err: unknown) =>
  err instanceof ApiError && err.status === 404 && err.code === "NOT_FOUND" && /no evaluation/i.test(err.message);

export async function latestEvaluation(): Promise<Maybe<EvaluationResponse>> {
  try {
    return { available: true, data: parseEvaluation(await request<unknown>("/api/evaluations/latest")) };
  } catch (err) {
    if (isNoEvaluationYet(err)) {
      return { available: true, data: { contract: "evaluation-summary-v1", state: "none", reason: "", how_to_run: "" } };
    }
    if (isMissingRoute(err)) return { available: false };
    throw err;
  }
}

/** Illustration only; rendered under a "Sample data" notice and never mixed with real numbers. */
export const SAMPLE_RISK: BrandRisk = {
  top_categories: [
    { category: "Product facts", count: 14 },
    { category: "Green claims", count: 9 },
    { category: "Tone", count: 6 },
    { category: "Easy to read", count: 4 },
  ],
  median_turnaround_minutes: 95,
  re_review_rate: 0.22,
  queue_age_minutes: { median: 180, oldest: 2880 },
  sample_size: 33,
};

// --- Evaluation summary contract "evaluation-summary-v1" (mirrors inkloom_verify/evaluation/summary.py) ---

export type EvalMetric = {
  key: string;
  label: string;
  explanation: string;
  /** Formatted by the engine exactly as in the Markdown report. */
  display: string;
  value: number | null;
  numerator: number | null;
  denominator: number | null;
  unavailable_reason: string | null;
};
export type EvalGate = {
  name: string;
  applies_to: string | null;
  op: string | null;
  current: number | null;
  baseline: number | null;
  change: number | null;
  status: string | null;
  enforced: boolean;
  violated: boolean;
  note: string;
};
export type EvalCase = {
  record_id: string;
  split: string;
  content: string;
  claims: { text: string; verdict: string; requires_human_review: boolean; review_reasons: string[] }[];
  expected: string;
  predicted: string;
  agrees: boolean;
  outcome: string;
  reason: string | null;
  passages: { doc_id: string; title: string | null; text: string; truncated: boolean }[];
  citations: { doc_id: string; quote: string; resolves: boolean; supports: boolean }[];
  corrections: { status: string; replacement_text: string | null; issues: string[] }[];
  requires_human_review: boolean;
};
export type Limitation = { topic: string; status: "measured" | "suspected" | "unsupported" | "not_implemented"; finding: string; evidence: string[] };
export type EvaluationSummary = {
  contract: "evaluation-summary-v1";
  state: "available";
  report_id: string | null;
  generated_at: string;
  outcome: { status: "passed" | "failed" | "incomplete"; reasons: string[] };
  source: { verdict_source: string; kind: string; is_model_quality: boolean; benchmark: boolean; production_statistics: boolean;
    git_commit: string | null; engine_version: string | null };
  dataset: { path: string | null; sha256: string | null; records: number | null; locked: boolean | null;
    labels: Record<string, number> | null; groups: Record<string, number> | null; human_reviewed: number | null };
  model: { provider: string | null; models: string[] | null; model_ids: string[] };
  prompt_versions: Record<string, string> | null;
  retrieval: { chunking?: Record<string, unknown>; retrieval?: Record<string, unknown> } | null;
  decision_policy: {
    policy: { version?: string; thresholds?: Record<string, unknown>; uses_model_confidence?: boolean } | null;
    calibration: { status?: string; split?: string } | null;
  } | null;
  counts: Record<string, number>;
  metrics: EvalMetric[];
  confusion: Record<string, Record<string, number>>;
  review: { auto_cleared?: number; auto_cleared_but_not_supported?: string[]; routed_by_label?: Record<string, number>;
    records_with_outcome?: number; excluded_without_outcome?: number };
  corrections: { proposed?: number; traceable?: number; attempts_by_status?: Record<string, number> };
  gates: EvalGate[];
  cases: EvalCase[];
  limitations: Limitation[];
  unavailable: Record<string, string>;
  stale: boolean;
  stale_reason: string | null;
};
export type EvaluationIncomplete = {
  contract: "evaluation-summary-v1";
  state: "incomplete";
  report_id: string | null;
  generated_at: string;
  verdict_source: string | null;
  error: string;
  limitations: Limitation[];
};
export type EvaluationNone = { contract: "evaluation-summary-v1"; state: "none"; reason: string; how_to_run: string };
export type EvaluationResponse = EvaluationSummary | EvaluationIncomplete | EvaluationNone;

const isObj = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);

/** Accepts only the documented contract; anything else is an error, never shown as data. */
export function parseEvaluation(x: unknown): EvaluationResponse {
  const bad = () => new ApiError(200, "BAD_RESPONSE", "The evaluation report does not match the expected format.", null);
  if (!isObj(x) || x.contract !== "evaluation-summary-v1") throw bad();
  if (x.state === "none" && typeof x.reason === "string") return x as EvaluationNone;
  if (x.state === "incomplete" && typeof x.error === "string" && Array.isArray(x.limitations)) return x as EvaluationIncomplete;
  if (
    x.state === "available" &&
    Array.isArray(x.metrics) && x.metrics.length === 8 &&
    Array.isArray(x.gates) && Array.isArray(x.cases) && Array.isArray(x.limitations) &&
    isObj(x.confusion) && isObj(x.outcome) && isObj(x.source) && isObj(x.dataset) && typeof x.generated_at === "string"
  ) {
    return x as EvaluationSummary;
  }
  throw bad();
}
