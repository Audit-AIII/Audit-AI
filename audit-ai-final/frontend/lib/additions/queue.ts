"use client";

import type { ReviewOut } from "@/lib/api/types";
import { request } from "./http";

/**
 * Review queue adapter: GET /api/reviews (the caller's own reviews, newest first, full ReviewOut).
 * Only real reviews are shown; there is no sample or placeholder data.
 */
export type QueueRow = {
  id: string;
  title: string;
  brandId: string | null;
  risk: "high" | "medium" | "low" | "none";
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
    createdAt: r.created_at,
    status: r.status,
    placeholder: r.findings.some((f) => f.category === "stub") || /^stub/i.test(r.engine?.provider ?? ""),
  };
}

export type QueueLoad = { rows: QueueRow[] };

/** Up to 100 of the caller's reviews (the backend's page limit), all statuses. */
export async function loadQueue(): Promise<QueueLoad> {
  const list = await request<ReviewOut[]>("/api/reviews?limit=100");
  return { rows: list.map(toRow) };
}
