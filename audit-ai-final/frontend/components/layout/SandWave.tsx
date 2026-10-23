"use client";

import { gsap } from "gsap";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import { SAND_EVENT, areaOf, setSandTransitioning, type SandGo } from "@/lib/sandWave";

/**
 * Page transition between the landing side and the workspace: a wall of sand with a curling
 * crest surges in from the right and covers the screen, the route changes underneath, then the
 * sand slumps and pours off the bottom (grains spilling) to reveal the new page.
 * Mounted once in the root layout so it survives the route change. Reduced motion: plain navigation.
 */

/* Wave drawing, viewBox 0 0 1400 1240 stretched over (100vw + 40vh) × 124vh.
   x 0–400: the curling crest (leading edge, travels left). y 0–120: the dune edge on top. */
const BODY =
  "M262 1240 C228 1100 206 940 214 780 C222 640 262 540 272 460 C280 396 256 350 214 340 C170 330 128 350 116 386 C108 412 124 432 146 428 C118 454 70 436 56 394 C38 340 70 270 140 226 C200 188 280 160 340 130 C420 90 470 60 560 72 C660 86 700 40 800 52 C900 64 950 22 1050 36 C1150 50 1200 14 1300 30 C1350 38 1380 30 1400 26 L1400 1240 Z";
const CURL = "M116 386 C108 412 124 432 146 428 C118 454 70 436 56 394 C38 340 70 270 140 226 C110 270 92 330 116 386 Z";
const CREST_FOAM =
  "M262 1240 C228 1100 206 940 214 780 C222 640 262 540 272 460 C280 396 256 350 214 340 C170 330 128 350 116 386 C108 412 124 432 146 428 M140 226 C200 188 280 160 340 130";
const TOP_FOAM = "M340 130 C420 90 470 60 560 72 C660 86 700 40 800 52 C900 64 950 22 1050 36 C1150 50 1200 14 1300 30 C1350 38 1380 30 1400 26";

// Deterministic scatter for the spilling grains (same on server and client).
const GRAINS = Array.from({ length: 44 }, (_, i) => {
  const r = (n: number) => ((Math.sin(i * 12.9898 + n * 78.233) * 43758.5453) % 1 + 1) % 1;
  // Rounded so the server-rendered style strings match the browser's exactly (hydration).
  const round = (n: number) => Math.round(n * 10) / 10;
  return { left: round(r(1) * 100), size: round(3 + r(2) * 6), delay: r(3) * 0.2, drift: (r(4) - 0.5) * 60 };
});

// Whole transition ≈ 1.9 s: cover 0.8 + paint gap ~0.1 + reveal ~1.0 (grains finish last).
const COVER_S = 0.8;
const REVEAL_S = 0.75;
const GRAIN_S = 0.75;

export function SandWave() {
  const router = useRouter();
  const pathname = usePathname();
  const root = useRef<HTMLDivElement>(null);
  const wave = useRef<HTMLDivElement>(null);
  const grains = useRef<HTMLDivElement>(null);
  // Path we are heading to while the sand covers the screen (null when idle).
  const pending = useRef<string | null>(null);
  const busy = useRef(false);
  // A navigation asked for while a wave is still running: started as soon as it finishes, so a
  // quick click (e.g. "Workspace" right after signing up) is never swallowed.
  const queued = useRef<SandGo | null>(null);
  const goRef = useRef<(g: SandGo) => void>(() => {});
  const finish = () => {
    busy.current = false;
    setSandTransitioning(false);
    const next = queued.current;
    queued.current = null;
    if (next) goRef.current(next);
  };

  // Start a transition: surge in, then navigate once covered.
  useEffect(() => {
    const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const go = ({ href, beforeNavigate }: SandGo) => {
      if (busy.current) {
        queued.current = { href, beforeNavigate };
        return;
      }
      const el = root.current;
      const w = wave.current;
      if (!el || !w || reduced()) {
        beforeNavigate?.();
        router.push(href);
        return;
      }
      busy.current = true;
      setSandTransitioning(true);
      router.prefetch(href);
      // Safety net: if the new route never arrives, never leave the sand over the page.
      window.setTimeout(() => {
        if (!pending.current) return;
        pending.current = null;
        gsap.to(el, { autoAlpha: 0, duration: 0.3, onComplete: finish });
      }, 7000);
      const crestW = window.innerHeight * 0.4;
      gsap.killTweensOf([w, ".sandwave__grain"]);
      gsap.set(el, { autoAlpha: 1 });
      gsap.set(w, { x: window.innerWidth + 40, y: window.innerHeight * 0.3, scaleY: 0.7, transformOrigin: "50% 100%" });
      gsap.to(w, {
        x: -crestW,
        y: 0,
        scaleY: 1,
        duration: COVER_S,
        ease: "power1.inOut",
        onComplete: () => {
          beforeNavigate?.();
          pending.current = new URL(href, window.location.href).pathname;
          router.push(href);
        },
      });
    };

    goRef.current = go;
    const onEvent = (e: Event) => go((e as CustomEvent<SandGo>).detail);

    // Same-origin links that cross between the landing side and the workspace.
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!a || a.target === "_blank" || a.hasAttribute("download")) return;
      const url = new URL(a.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (areaOf(url.pathname) === areaOf(window.location.pathname)) return;
      e.preventDefault();
      go({ href: url.pathname + url.search + url.hash });
    };

    window.addEventListener(SAND_EVENT, onEvent);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener(SAND_EVENT, onEvent);
      document.removeEventListener("click", onClick, true);
    };
  }, [router]);

  // Reveal once the new route is on screen: the sand slumps down and grains pour off.
  useEffect(() => {
    const target = pending.current;
    if (!target) return;
    const arrived = target === "/" ? pathname === "/" : pathname === target || pathname.startsWith(`${target}/`);
    if (!arrived) return;
    pending.current = null;

    const el = root.current;
    const w = wave.current;
    const g = grains.current;
    if (!el || !w || !g) return;
    let frame = 0;
    const reveal = () => {
      const h = window.innerHeight;
      const tl = gsap.timeline({
        onComplete: () => {
          gsap.set(el, { autoAlpha: 0 });
          finish();
        },
      });
      // collapse: the wall slumps (squashes) and pours down off the screen
      tl.to(w, { scaleY: 0.55, duration: REVEAL_S * 0.45, ease: "power2.in" }, 0);
      tl.to(w, { y: h * 1.3, duration: REVEAL_S, ease: "power2.in" }, 0.1);
      tl.fromTo(
        g.children,
        { y: () => -20 - Math.random() * h * 0.2, x: 0, autoAlpha: 1 },
        {
          y: () => h * (0.75 + Math.random() * 0.4),
          x: (i) => GRAINS[i].drift,
          autoAlpha: 0,
          duration: GRAIN_S,
          ease: "power2.in",
          delay: (i) => GRAINS[i].delay,
        },
        0.08,
      );
    };
    // Let the new page paint under the sand first.
    frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => window.setTimeout(reveal, 60));
    });
    return () => cancelAnimationFrame(frame);
  }, [pathname]);

  return (
    <div ref={root} className="sandwave" aria-hidden="true">
      <div ref={wave} className="sandwave__wave">
        <svg className="sandwave__svg" viewBox="0 0 1400 1240" preserveAspectRatio="none" focusable="false">
          <defs>
            {/* wet and dark at the leading face, drier towards the back */}
            <linearGradient id="sandwave-fill" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" className="sandwave__wet-front" />
              <stop offset=".3" className="sandwave__wet-mid" />
              <stop offset="1" className="sandwave__wet-back" />
            </linearGradient>
          </defs>
          <g filter="url(#shell-sand)">
            <path d={BODY} fill="url(#sandwave-fill)" />
          </g>
          <path className="sandwave__curl" d={CURL} />
          <path className="sandwave__foam sandwave__foam--crest" d={CREST_FOAM} />
          <path className="sandwave__foam sandwave__foam--top" d={TOP_FOAM} />
        </svg>
      </div>
      <div ref={grains} className="sandwave__grains">
        {GRAINS.map((p, i) => (
          <span key={i} className="sandwave__grain" style={{ left: `${p.left}%`, width: `${p.size}px`, height: `${p.size}px` }} />
        ))}
      </div>
    </div>
  );
}
