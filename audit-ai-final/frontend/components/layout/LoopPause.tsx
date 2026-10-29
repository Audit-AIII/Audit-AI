"use client";

import { useEffect } from "react";

/**
 * Pauses the endless decorative loops of a `[data-loop]` section while it is more than a screen
 * away (`data-paused`, see base.css). The Sources tide lines animate mask-position, which repaints
 * the page on the main thread every frame even far below the fold: half of the landing page's idle
 * paints (PERF_BASELINE.md). They run again before the section scrolls into view.
 */
export function LoopPause() {
  useEffect(() => {
    const nodes = document.querySelectorAll<HTMLElement>("[data-loop]");
    if (!nodes.length || !("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.target.toggleAttribute("data-paused", !e.isIntersecting)),
      { rootMargin: "100% 0px" },
    );
    nodes.forEach((n) => io.observe(n));
    return () => {
      io.disconnect();
      nodes.forEach((n) => n.removeAttribute("data-paused"));
    };
  }, []);

  return null;
}
