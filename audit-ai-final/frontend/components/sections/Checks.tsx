"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Heading } from "@/components/primitives/Heading";
import { Swatch, type CheckKind } from "@/components/primitives/Swatch";
import { SandDrift, Shore, type ShellSpot } from "@/components/layout/Shore";

gsap.registerPlugin(ScrollTrigger);

// `soon`: shown on the page as "Coming next" (Tone and Visuals are not built yet).
const CHECKS: { kind: CheckKind; title: string; line: string; soon?: boolean }[] = [
  { kind: "tone", title: "Tone", line: "Does it sound like your brand?", soon: true },
  { kind: "terminology", title: "Wording", line: "Product names and terms, spelled your way." },
  { kind: "facts", title: "Facts", line: "Numbers and dates match what you approved." },
  { kind: "claims", title: "Claims", line: "Big promises need proof." },
  { kind: "visual", title: "Visuals", line: "Colours and logos match your brand.", soon: true },
  { kind: "accessibility", title: "Easy to read", line: "Clear for everyone, first time." },
];

// Resting tilt of each card while stacked (deg), so the pile looks hand-dealt.
const TILT = [-7, 5, -3, 8, -5, 3];

/** Six checks as six swatch cards. On desktop they are dealt from a stacked pile into the grid, scrubbed to scroll. */
// Beach decor in the open sand around the heading (hidden below 900px).
const SHELLS: ShellSpot[] = [
  { kind: "scallop", x: "62%", y: "70px", size: 129, rotate: -14 },
  { kind: "spiral", x: "79%", y: "150px", size: 67, rotate: 30 },
  { kind: "pebble", x: "73%", y: "236px", size: 26, rotate: 12 },
  { kind: "pebble", x: "86%", y: "92px", size: 18, rotate: -20 },
  { kind: "tide", x: "44%", y: "6px", size: 600 },
  { kind: "conch", x: "88%", y: "210px", size: 70, rotate: -18 },
  { kind: "pearls", x: "75%", y: "60px", size: 54 },
  { kind: "glass", x: "92%", y: "130px", size: 36, rotate: 20, tone: "sea" },
  { kind: "pebble", x: "69%", y: "250px", size: 33, rotate: 10, tone: "terracotta" },
  { kind: "pebble", x: "84%", y: "300px", size: 27, rotate: -25, tone: "sage" },
  { kind: "pebble", x: "58%", y: "250px", size: 24, tone: "slate" },
];

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
      // Sand drifts settle in around the cards once they have landed.
      gsap.from(list.querySelectorAll(".checks__drift"), {
        opacity: 0,
        y: 10,
        ease: "none",
        stagger: 0.05,
        scrollTrigger: { trigger: list, start: "center 72%", end: "center 58%", scrub: 0.8 },
      });
    });
    return () => mm.revert();
  }, []);

  return (
    <section id="checks" className="section checks" aria-labelledby="checks-title">
      <Shore shells={SHELLS} />
      <div className="container">
        <div className="head-grid checks__head">
          <Heading id="checks-title" className="checks__title" data-r="up">
            Six checks, two live today
          </Heading>
          <p className="t-lead checks__intro" data-r="up">
            Facts, Claims, Wording and Easy to read check every draft today; Tone and Visuals are coming next. Each fact or claim we flag tells you which document it came from.
          </p>
        </div>
        <ul ref={grid} className="checks__grid">
          {CHECKS.map((c, i) => (
            <li key={c.kind} className="checks__item">
              <Swatch kind={c.kind} className="checks__swatch" />
              <SandDrift variant={i} className="checks__drift" />
              <h3 className="t-title checks__name">
                {c.title}
                {c.soon && <span className="checks__soon">Coming next</span>}
              </h3>
              <p className="t-body checks__line">{c.line}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
