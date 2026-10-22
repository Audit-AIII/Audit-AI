"use client";

import { useEffect } from "react";

/**
 * One observer for every `[data-r]` element on the page ("up" | "scale" | "fade").
 * Each reveal fires once. Children of `[data-stagger]` get a 70ms step delay via `--d`.
 */
export function Reveal() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>("[data-r]"));

    document.querySelectorAll<HTMLElement>("[data-stagger]").forEach((group) => {
      group.querySelectorAll<HTMLElement>(":scope > [data-r]").forEach((child, i) => {
        child.style.setProperty("--d", `${i * 70}ms`);
      });
    });

    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !("IntersectionObserver" in window)) {
      nodes.forEach((n) => n.classList.add("is-in"));
      return;
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          entry.target.classList.add("is-in");
          io.unobserve(entry.target);
        }
      },
      { threshold: 0.15, rootMargin: "0px 0px -10% 0px" },
    );
    nodes.forEach((n) => io.observe(n));
    return () => io.disconnect();
  }, []);

  return null;
}
