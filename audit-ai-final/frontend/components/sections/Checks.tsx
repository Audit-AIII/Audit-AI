"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Heading } from "@/components/primitives/Heading";
import { Swatch, type CheckKind } from "@/components/primitives/Swatch";

gsap.registerPlugin(ScrollTrigger);

const CHECKS: { kind: CheckKind; title: string; line: string }[] = [
  { kind: "tone", title: "Tone", line: "Does it sound like your brand?" },
  { kind: "terminology", title: "Wording", line: "Product names and terms, spelled your way." },
  { kind: "facts", title: "Facts", line: "Numbers and dates match what you approved." },
  { kind: "claims", title: "Claims", line: "Big promises need proof." },
  { kind: "visual", title: "Visuals", line: "Colours and logos match your brand." },
  { kind: "accessibility", title: "Easy to read", line: "Clear for everyone, first time." },
];

// Resting tilt of each card while stacked (deg), so the pile looks hand-dealt.
const TILT = [-7, 5, -3, 8, -5, 3];

/** Six checks as six swatch cards. On desktop they are dealt from a stacked pile into the grid, scrubbed to scroll. */
export function Checks() {
  const grid = useRef<HTMLUListElement>(null);

  useEffect(() => {
    const list = grid.current;
    if (!list) return;
    const mm = gsap.matchMedia();
    mm.add("(min-width: 768px) and (prefers-reduced-motion: no-preference)", () => {
      const cards = Array.from(list.querySelectorAll<HTMLElement>(".checks__swatch"));
      // Layout offsets inside the grid (unaffected by transforms, so refreshes stay stable).
      const pileX = () => list.clientWidth / 2;
      const pileY = () => (cards[0]?.offsetHeight ?? 0) * 0.55;
      gsap.set(cards, { zIndex: (i) => cards.length - i });
      gsap.from(cards, {
        x: (i) => pileX() - (cards[i].offsetLeft + cards[i].offsetWidth / 2) + i * 6,
        y: (i) => pileY() - (cards[i].offsetTop + cards[i].offsetHeight / 2) + i * 4,
        rotation: (i) => TILT[i],
        scale: 0.81,
        ease: "none",
        stagger: 0.1,
        // Deal finishes by the time the grid is mid-screen; stagger + light scrub lag keep it readable.
        scrollTrigger: { trigger: list, start: "top 100%", end: "center 65%", scrub: 0.8, invalidateOnRefresh: true },
      });
    });
    return () => mm.revert();
  }, []);

  return (
    <section id="checks" className="section checks" aria-labelledby="checks-title">
      <div className="container">
        <div className="head-grid checks__head">
          <Heading id="checks-title" className="checks__title" data-r="up">
            Six checks before anything ships
          </Heading>
          <p className="t-lead checks__intro" data-r="up">
            Every draft goes through six checks. Each problem we flag tells you which rule or document it came from.
          </p>
        </div>
        <ul ref={grid} className="checks__grid">
          {CHECKS.map((c) => (
            <li key={c.kind} className="checks__item">
              <Swatch kind={c.kind} className="checks__swatch" />
              <h3 className="t-title checks__name">{c.title}</h3>
              <p className="t-body checks__line">{c.line}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
