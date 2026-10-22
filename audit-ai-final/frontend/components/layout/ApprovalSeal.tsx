"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

/**
 * The hollow ring from the "Private stays private" disc lifts out, travels down with scroll,
 * shrinks and settles into the "Approved" circle of the approval path, which then shows a tick.
 * Rendered inside the page sheet (position: relative); positions are measured relative to it.
 * Without motion the Approved circle simply shows its tick.
 */
export function ApprovalSeal() {
  const ring = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ring.current;
    const sheet = el?.parentElement;
    const from = document.querySelector<HTMLElement>("[data-seal-source]");
    const to = document.querySelector<HTMLElement>("[data-seal-target]");
    const step = to?.closest<HTMLElement>(".roles__step");
    if (!el || !sheet || !from || !to || !step) return;

    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      sheet.setAttribute("data-seal-anim", "");
      const centre = (n: HTMLElement) => {
        const r = n.getBoundingClientRect();
        const s = sheet.getBoundingClientRect();
        return { x: r.left + r.width / 2 - s.left, y: r.top + r.height / 2 - s.top, w: r.width };
      };
      const size = () => from.offsetWidth;
      const place = () => {
        const a = centre(from);
        gsap.set(el, { width: size(), height: size(), left: a.x - size() / 2, top: a.y - size() / 2 });
      };
      place();

      const tl = gsap.timeline({
        scrollTrigger: {
          trigger: from,
          start: "center 60%",
          endTrigger: to,
          end: "center 60%",
          scrub: 0.6,
          invalidateOnRefresh: true,
          onRefreshInit: place,
          onUpdate: (self) => step.classList.toggle("is-sealed", self.progress > 0.97),
        },
      });
      tl.fromTo(el, { "--lift": 0 }, { "--lift": 1, duration: 0.12, ease: "power1.out" }, 0)
        .fromTo(
          el,
          { x: 0, y: 0, scale: 1 },
          {
            x: () => centre(to).x - centre(from).x,
            y: () => centre(to).y - centre(from).y,
            scale: () => to.offsetWidth / size(),
            duration: 1,
            ease: "power1.inOut",
          },
          0,
        )
        .to(el, { opacity: 0, duration: 0.04 }, 0.98);

      return () => {
        sheet.removeAttribute("data-seal-anim");
        step.classList.remove("is-sealed");
      };
    });
    return () => mm.revert();
  }, []);

  return (
    <span ref={ring} className="seal" aria-hidden="true">
      <span className="seal__ring" />
    </span>
  );
}
