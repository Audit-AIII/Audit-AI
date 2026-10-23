"use client";

import type { ReviewOut } from "@/lib/api/types";
import { isMissingRoute, request } from "./http";

/**
 * Review queue adapter. GET /api/reviews (list) does not exist yet: today it answers 405 because
 * only POST is defined on that path. Until it lands, the queue shows:
 *   - REAL reviews this browser knows about (ids the workspace stored when they were sent or opened:
 *     "audit-ai.review-text-index" and "audit-ai.last-review", read-only), each fetched live;
 *   - clearly labelled sample rows, with no counts drawn from them.
 */
export type QueueRow = {
  id: string;
  title: string;
  brandId: string | null;
  risk: "high" | "medium" | "low" | "none";
  requiredRole: string | null;
  createdAt: string;
  status: string;
  placeholder: boolean;
};

const RISK: Record<string, number> = { critical: 3, high: 3, medium: 2, low: 1 };
export function toRow(r: ReviewOut): QueueRow {
  const real = r.findings.filter((f) => f.category !== "stub");
  const top = Math.max(0, ...real.filter((f) => f.verification_status !== "supported").map((f) => RISK[f.severity] ?? 0));
  return {
    id: r.id,
    title: r.title ?? "Untitled draft",
    brandId: r.brand_id ?? null,
    risk: (["none", "low", "medium", "high"] as const)[top],
    requiredRole: r.required_reviewer_role,
    createdAt: r.created_at,
    status: r.status,
    placeholder: r.findings.some((f) => f.category === "stub") || /^stub/i.test(r.engine?.provider ?? ""),
  };
}

function knownIds(): string[] {
  try {
    const ids: string[] = JSON.parse(window.localStorage.getItem("audit-ai.review-text-index") ?? "[]");
    const last = window.localStorage.getItem("audit-ai.last-review");
    return [...new Set([...(last ? [last] : []), ...ids])].slice(0, 20);
  } catch {
    return [];
  }
}

export type QueueLoad = { source: "api" | "browser"; rows: QueueRow[]; failed: number };

export async function loadQueue(): Promise<QueueLoad> {
  try {
    const list = await request<ReviewOut[]>("/api/reviews?status=needs_human_review");
    return { source: "api", rows: list.map(toRow), failed: 0 };
  } catch (err) {
    if (!isMissingRoute(err)) throw err;
  }
  const results = await Promise.allSettled(knownIds().map((id) => request<ReviewOut>(`/api/reviews/${encodeURIComponent(id)}`)));
  const rows = results.flatMap((r) => (r.status === "fulfilled" ? [toRow(r.value)] : []));
  return { source: "browser", rows, failed: results.length - rows.length };
}

/** Illustration only. Never counted, never mixed into real rows. */
export const SAMPLE_ROWS: QueueRow[] = [
  { id: "sample-1", title: "Aero earbuds launch page", brandId: null, risk: "high", requiredRole: "legal_reviewer", createdAt: "", status: "needs_human_review", placeholder: false },
  { id: "sample-2", title: "Spring newsletter", brandId: null, risk: "medium", requiredRole: "brand_manager", createdAt: "", status: "needs_human_review", placeholder: false },
  { id: "sample-3", title: "Product page: steel bottle", brandId: null, risk: "low", requiredRole: "brand_manager", createdAt: "", status: "completed", placeholder: false },
];
