"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const HEADER_CLEARANCE = 88; // fixed 68px header + breathing room; matches scroll-padding-top in base.css

/** Lenis smooth scroll driven by the GSAP ticker so ScrollTrigger scrubs stay in sync. Off for reduced motion. */
export function SmoothScroll() {
  // In-page links: open a <details> target (FAQ answers) and briefly outline where the link landed.
  useEffect(() => {
    const onClick = (e: MouseEvent) => {
      const link = (e.target as Element | null)?.closest<HTMLAnchorElement>('a[href*="#"]');
      if (!link || link.pathname !== location.pathname) return;
      const target = link.hash.length > 1 ? document.getElementById(decodeURIComponent(link.hash.slice(1))) : null;
      if (!target) return;
      if (target instanceof HTMLDetailsElement) target.open = true;
      target.classList.remove("is-targeted");
      void target.offsetWidth; // restart the animation on repeat clicks
      target.classList.add("is-targeted");
      window.setTimeout(() => target.classList.remove("is-targeted"), 2000);
    };
    document.addEventListener("click", onClick);
    return () => document.removeEventListener("click", onClick);
  }, []);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const lenis = new Lenis({ autoRaf: false, anchors: { offset: -HEADER_CLEARANCE } });
    lenis.on("scroll", ScrollTrigger.update);
    const tick = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);

    return () => {
      gsap.ticker.remove(tick);
      lenis.destroy();
    };
  }, []);

  return null;
}
