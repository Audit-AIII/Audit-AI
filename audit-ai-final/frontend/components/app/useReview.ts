"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api/client";
import { withToneRule } from "@/lib/additions/tone";
import type { ReviewOut } from "@/lib/api/types";
import { getLastReviewId, setLastReviewId } from "@/lib/workspace";

export type ReviewLoad =
  | { state: "none" }
  | { state: "loading" }
  | { state: "ok"; review: ReviewOut }
  | { state: "error"; message: string; requestId: string | null };

/** The review a stage works on: ?id= first, else the last review opened in this browser. */
export function useReviewId(): string | null {
  const fromUrl = useSearchParams().get("id");
  // Client-only render (AppShell waits for the session), so localStorage is safe to read here.
  const [fallback] = useState(getLastReviewId);
  return fromUrl ?? fallback;
}

/** Loads GET /api/reviews/{id}; `reload()` fetches it again (e.g. after a decision). */
export function useReview(id: string | null) {
  const [load, setLoad] = useState<ReviewLoad>(id ? { state: "loading" } : { state: "none" });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!id) return;
    let live = true;
    api
      .review(id)
      .then((review) => {
        if (!live) return;
        setLastReviewId(review.id);
        setLoad({ state: "ok", review: withToneRule(review) });
      })
      .catch((err) => {
        if (!live) return;
        const message =
          err instanceof ApiError && err.status === 404
            ? "We couldn’t find this review. It may belong to another organisation, or the link is wrong."
            : err instanceof ApiError
              ? err.userMessage
              : "Something went wrong. Please try again.";
        setLoad({ state: "error", message, requestId: err instanceof ApiError ? err.requestId : null });
      });
    return () => {
      live = false;
    };
  }, [id, tick]);

  return { load, reload };
}
