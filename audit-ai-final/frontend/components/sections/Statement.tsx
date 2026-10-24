"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const LINES = ["Claims need proof.", "Sources stay current.", "People decide."];

/**
 * Statement band: a paper sheet rises over the sinking hero (scale .94 → 1); a roller travels down
 * the sheet and presses each line in as it passes. Without JS or with reduced motion, all lines are pressed.
 */
export function Statement() {
  const section = useRef<HTMLElement>(null);
  const flap = useRef<HTMLDivElement>(null);
  const roller = useRef<HTMLSpanElement>(null);
  const lines = useRef<HTMLSpanElement[]>([]);

  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      el.setAttribute("data-press", "");
      const words = lines.current;
      const stmt = words[0]?.parentElement;
      words.forEach((w) => w.setAttribute("data-pressed", "0"));
      const pressed = words.map(() => "0");
      let shown = "";
      const geom = { first: 0, last: 0, marks: [] as number[] };
      const measure = () => {
        if (!words.length) return;
        const end = words[words.length - 1];
        geom.first = words[0].offsetTop - 20;
        geom.last = end.offsetTop + end.offsetHeight + 20;
        geom.marks = words.map((w) => w.offsetTop + w.offsetHeight * 0.6);
      };
      measure();

      gsap.fromTo(
        flap.current,
        { scale: 0.94 },
        { scale: 1, ease: "none", scrollTrigger: { trigger: el, start: "top bottom", end: "top top", scrub: true } },
      );

      ScrollTrigger.create({
        trigger: el,
        start: "top top",
        end: "bottom bottom",
        scrub: true,
        // Line positions are measured once per refresh (load / resize), not on every scroll frame:
        // reading offsetTop right after the style writes below forced a layout each frame.
        onRefresh: measure,
        onUpdate: (self) => {
          if (!stmt || !roller.current) return;
          // Roller sweeps from just above the first line to just below the last.
          const y = geom.first + (geom.last - geom.first) * Math.min(1, self.progress * 1.15);
          roller.current.style.transform = `translateY(${y}px)`;
          const opacity = self.progress > 0 && self.progress < 0.9 ? "1" : "0";
          if (opacity !== shown) roller.current.style.opacity = shown = opacity;
          // Only touch a line when its state flips (each write re-styles the statement).
          words.forEach((w, i) => {
            const v = y > geom.marks[i] ? "1" : "0";
            if (v !== pressed[i]) w.setAttribute("data-pressed", (pressed[i] = v));
          });
        },
      });

      return () => {
        el.removeAttribute("data-press");
        words.forEach((w) => w.removeAttribute("data-pressed"));
      };
    });
    return () => mm.revert();
  }, []);

  return (
    <section ref={section} className="statement" aria-labelledby="statement-title">
      <div className="statement__stage">
        <div ref={flap} className="statement__flap board">
          <h2 id="statement-title" className="statement__lines">
            {LINES.map((line, i) => (
              <span
                key={line}
                ref={(n) => {
                  if (n) lines.current[i] = n;
                }}
                className="statement__line relief-pressed grain-text"
                data-text={line}
              >
                {line}
              </span>
            ))}
            <span ref={roller} className="statement__roller" aria-hidden="true" />
          </h2>
          {/* COPY TO REVIEW: §15 gives no text for this note. */}
          <div className="statement__note">
            <p className="t-lead">Every flag points to the document behind it.</p>
            <p className="t-body">If nothing proves a line, it is marked “not proven yet”, never “wrong”, until you decide.</p>
          </div>
        </div>
      </div>
    </section>
  );
}
