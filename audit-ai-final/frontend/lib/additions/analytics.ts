"use client";

import { isMissingRoute, request } from "./http";

/**
 * Insights + Trust Scorecard adapters. Neither endpoint exists on the backend yet:
 *   GET  /api/analytics/brand-risk   (404 today)
 *   GET  /api/evaluations/latest     (proposed; 404 today)
 *   POST /api/evaluations            (proposed "Run evaluation"; 404 today)
 * services/verification/EVAL.md states no verifier results exist yet, so nothing here may show a
 * measured number unless one of these routes returns it. Missing route -> { available: false }.
 */
export type BrandRisk = {
  top_categories: { category: string; count: number }[];
  median_turnaround_minutes: number | null;
  re_review_rate: number | null;
  queue_age_minutes: { median: number | null; oldest: number | null };
  sample_size: number;
};
export type Evaluation = {
  catch_rate: number | null;
  false_positive_rate: number | null;
  per_check: { check: string; catch_rate: number | null; false_positive_rate: number | null; n: number }[];
  sample_size: number;
  run_at: string;
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
export const latestEvaluation = () => optional<Evaluation>("/api/evaluations/latest");
export const runEvaluation = () => optional<Evaluation>("/api/evaluations", { method: "POST" });

/** Targets from the product brief (CLAUDE.md "Trust Scorecard": 85% catch rate / 15% false positives). */
export const TARGETS = { catchRate: 0.85, falsePositiveRate: 0.15 };

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
export const SAMPLE_EVAL: Evaluation = {
  catch_rate: 0.81,
  false_positive_rate: 0.12,
  per_check: [
    { check: "Facts", catch_rate: 0.9, false_positive_rate: 0.08, n: 12 },
    { check: "Claims", catch_rate: 0.75, false_positive_rate: 0.15, n: 8 },
    { check: "Tone", catch_rate: 0.7, false_positive_rate: 0.2, n: 6 },
  ],
  sample_size: 26,
  run_at: "",
};
