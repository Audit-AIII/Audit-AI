"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import type { ReviewOut } from "@/lib/api/types";
import { getLastReviewId, getReviewText } from "@/lib/workspace";
import { request } from "./http";
import { withToneRule } from "./tone";

/**
 * Read-only review loader for the additive pages. Unlike components/app/useReview it never
 * writes the workspace's "last review" (so opening a new page can't change what Decide/Record show).
 */
export type ReviewState = { state: "none" } | { state: "loading" } | { state: "ok"; review: ReviewOut } | { state: "error"; error: unknown };

/** ?id= first, else the last review the workspace opened. */
export function useReviewParam(): string | null {
  const fromUrl = useSearchParams().get("id");
  // Client-only render (AppShell waits for the session), so localStorage is safe here.
  const [fallback] = useState(getLastReviewId);
  return fromUrl ?? fallback;
}

export function useReviewData(id: string | null) {
  const [value, setValue] = useState<ReviewState>(id ? { state: "loading" } : { state: "none" });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!id) return;
    let live = true;
    request<ReviewOut>(`/api/reviews/${encodeURIComponent(id)}`)
      .then((review) => live && setValue({ state: "ok", review: withToneRule(review) }))
      .catch((error) => live && setValue({ state: "error", error }));
    return () => {
      live = false;
    };
  }, [id, tick]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { value, reload };
}

/** The text the spans point into: the API's copy first, then this browser's copy from submit time. */
export const textOf = (r: ReviewOut): string | null => r.text ?? getReviewText(r.id);
