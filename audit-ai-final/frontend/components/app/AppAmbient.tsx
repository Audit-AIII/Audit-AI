"use client";

import { useEffect, useRef } from "react";
import { Shore, type ShellSpot } from "@/components/layout/Shore";

/**
 * Workspace backdrop, from the landing page's kit: a slow warm paper sheen drifting across the
 * board (16s, like the hero light) that leans toward the pointer, two blind-embossed discs, and
 * the landing page's beach finds (Shore: shells, conch, pearls, sea glass, pebbles, a drifting
 * tide line). The finds sit in the open strip beside the page title and the tide low on the
 * screen; the panels slide over them. Decorative only: aria-hidden, no pointer events.
 * Pointer-follow only on fine pointers; reduced motion: everything still.
 */
const FINDS: ShellSpot[] = [
  { kind: "tide", x: "-6%", y: "82vh", size: 760 },
  { kind: "conch", x: "77%", y: "70px", size: 88, rotate: -24 },
  { kind: "scallop", x: "71%", y: "96px", size: 66, rotate: 16 },
  { kind: "pearls", x: "81%", y: "122px", size: 44 },
  { kind: "glass", x: "75%", y: "140px", size: 30, rotate: -12, tone: "sea" },
  { kind: "pebble", x: "67%", y: "84px", size: 24, rotate: 20, tone: "terracotta" },
  { kind: "pebble", x: "70%", y: "146px", size: 20, tone: "slate" },
  { kind: "spiral", x: "88%", y: "60vh", size: 70, rotate: 30 },
  { kind: "star", x: "1.5%", y: "72vh", size: 60, rotate: -14 },
  { kind: "pebble", x: "93%", y: "68vh", size: 24, tone: "ochre" },
];
export function AppAmbient() {
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = root.current;
    if (!el || !window.matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)").matches) return;
    const target = { x: 0, y: 0 };
    const pos = { x: 0, y: 0 };
    let frame = 0;
    const step = () => {
      pos.x += (target.x - pos.x) * 0.06;
      pos.y += (target.y - pos.y) * 0.06;
      el.style.setProperty("--px", pos.x.toFixed(4));
      el.style.setProperty("--py", pos.y.toFixed(4));
      frame = Math.abs(target.x - pos.x) + Math.abs(target.y - pos.y) > 0.001 ? requestAnimationFrame(step) : 0;
    };
    const onMove = (e: PointerEvent) => {
      target.x = (e.clientX / window.innerWidth) * 2 - 1;
      target.y = (e.clientY / window.innerHeight) * 2 - 1;
      if (!frame) frame = requestAnimationFrame(step);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div ref={root} className="app__ambient" aria-hidden="true">
      <span className="app__light-frame">
        <span className="app__light" />
      </span>
      <span className="app__disc app__disc--raised" />
      <span className="app__disc app__disc--pressed" />
      <Shore shells={FINDS} />
    </div>
  );
}
