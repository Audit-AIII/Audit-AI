"use client";

import type { ReviewOut } from "@/lib/api/types";
import { request } from "./http";

/**
 * Versioning calls for the Correction Editor (services/api routers/content.py, reviews.py):
 *   POST /api/content/{content_item_id}/versions   {text}  -> new version + its review (needs submit)
 *   GET  /api/content/{content_item_id}/history            -> versions, reviews and decisions
 *   POST /api/reviews/{review_id}/rerun                    -> a new review of the same version (needs submit)
 * content_item_id comes from ReviewOut.content_item_id; older backends don't send it, so callers
 * get null from itemIdOf() and must show a "needs backend field" note instead of failing.
 */
export type NewVersionOut = { content_version_id: string; version_number: number; is_current: boolean; review: ReviewOut };
export type HistoryOut = {
  content_item_id: string;
  title: string;
  versions: {
    id: string;
    version_number: number;
    is_current: boolean;
    created_at: string;
    reviews: { id: string; status: string; created_at: string }[];
    decisions: { action: string; created_at: string; note: string | null }[];
  }[];
};

export const itemIdOf = (r: ReviewOut): string | null => r.content_item_id ?? null;

export const saveNewVersion = (contentItemId: string, text: string) =>
  request<NewVersionOut>(`/api/content/${encodeURIComponent(contentItemId)}/versions`, { method: "POST", body: { text } });

export const history = (contentItemId: string) => request<HistoryOut>(`/api/content/${encodeURIComponent(contentItemId)}/history`);

export const rerun = (reviewId: string, idempotencyKey: string) =>
  request<ReviewOut>(`/api/reviews/${encodeURIComponent(reviewId)}/rerun`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey } });
