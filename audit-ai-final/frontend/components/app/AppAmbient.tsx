"use client";

import { useEffect, useRef } from "react";

/**
 * Workspace backdrop, from the landing page's kit: a slow warm paper sheen drifting across the
 * board (16s, like the hero light) that leans toward the pointer, and two blind-embossed discs
 * (one raised, one pressed) far behind the panels. Decorative only: aria-hidden, no pointer
 * events. Pointer-follow only on fine pointers; reduced motion: everything still.
 */
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
    </div>
  );
}
