"use client";

import { useEffect, useRef } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Button } from "@/components/primitives/Button";
import { Heading } from "@/components/primitives/Heading";

gsap.registerPlugin(ScrollTrigger);

// COPY TO REVIEW: step descriptions expand the §15 parentheticals into sentences.
const STEPS = [
  { title: "Import what's approved", copy: "Bring in your guidelines, fact sheet, approved claims and assets.", visual: "import" },
  { title: "Submit the draft", copy: "Paste text or upload a document or an image.", visual: "submit" },
  {
    title: "Review with evidence",
    copy: "Each finding explains itself, suggests a fix and re-checks it.",
    visual: "review",
  },
  { title: "Approve and record", copy: "The right role signs off, and every decision lands in the audit trail.", visual: "approve" },
] as const;

function StepVisual({ kind }: { kind: (typeof STEPS)[number]["visual"] }) {
  switch (kind) {
    case "import":
      return (
        <div className="pv pv--import">
          {["Guidelines", "Fact sheet", "Claims", "Assets"].map((t) => (
            <span key={t} className="pv__tag">
              {t}
            </span>
          ))}
        </div>
      );
    case "submit":
      return (
        <div className="pv pv--submit">
          <span className="pv__page">
            <i />
            <i />
            <i />
            <i />
          </span>
        </div>
      );
    case "review":
      return (
        <div className="pv pv--review">
          <span className="pv__window">
            <i />
            <i className="pv__flag" />
            <i />
          </span>
        </div>
      );
    case "approve":
      return (
        <div className="pv pv--approve">
          <span className="pv__stamp">Approved</span>
        </div>
      );
  }
}

/**
 * Four moves on a horizontal track inside a die-cut window. On desktop the section pins and the
 * track slides with scroll; on mobile / reduced motion it is a swipeable row with scroll-snap.
 */
export function Process() {
  const section = useRef<HTMLElement>(null);
  const channel = useRef<HTMLDivElement>(null);
  const track = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const el = section.current;
    if (!el || !channel.current || !track.current) return;
    const ch = channel.current;
    const tr = track.current;
    const mm = gsap.matchMedia();
    mm.add("(min-width: 768px) and (prefers-reduced-motion: no-preference)", () => {
      el.setAttribute("data-track", "");
      const distance = () => Math.max(0, tr.scrollWidth - ch.clientWidth);
      const setDistance = () => el.style.setProperty("--process-distance", `${distance()}px`);
      setDistance();
      const tween = gsap.to(tr, {
        x: () => -distance(),
        ease: "none",
        scrollTrigger: {
          trigger: el,
          start: "top top",
          end: "bottom bottom",
          scrub: true,
          invalidateOnRefresh: true,
          onRefreshInit: setDistance,
        },
      });
      ScrollTrigger.refresh();
      return () => {
        tween.kill();
        el.removeAttribute("data-track");
        el.style.removeProperty("--process-distance");
      };
    });
    return () => mm.revert();
  }, []);

  return (
    <section ref={section} id="process" className="process" aria-labelledby="process-title">
      <div className="process__stage">
        <div className="container process__head">
          <Heading id="process-title" className="process__title" data-r="up">
            Draft to approved in four moves
          </Heading>
        </div>
        <div className="container process__frame">
          <div ref={channel} className="process__channel ply">
            <ol ref={track} className="process__track">
              {STEPS.map((s, i) => (
                <li key={s.title} className="process__step card">
                  <span className="t-caption">Step {i + 1}</span>
                  <h3 className="t-title process__name">{s.title}</h3>
                  <p className="t-body process__copy">{s.copy}</p>
                  <StepVisual kind={s.visual} />
                </li>
              ))}
              <li className="process__end">
                <Button href="#contact">Try it on one draft</Button>
              </li>
            </ol>
          </div>
        </div>
      </div>
    </section>
  );
}
