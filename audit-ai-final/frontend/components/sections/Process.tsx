"use client";

import { useEffect, useRef, useState } from "react";
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
  const [active, setActive] = useState(0);

  useEffect(() => {
    const el = section.current;
    if (!el || !channel.current || !track.current) return;
    const ch = channel.current;
    const tr = track.current;
    const mm = gsap.matchMedia();
    mm.add("(min-width: 768px) and (prefers-reduced-motion: no-preference)", () => {
      el.setAttribute("data-track", "");
      // The pinned section is split into one scroll band per step. Crossing into a band slides
      // that step in with a short eased tween, so exactly one step is ever shown at rest.
      const distance = () => Math.max(0, tr.scrollWidth - ch.clientWidth);
      const n = STEPS.length;
      const setDistance = () => el.style.setProperty("--process-distance", `${distance()}px`);
      setDistance();
      let current = -1;
      const show = (i: number, instant = false) => {
        if (i === current) return;
        current = i;
        setActive(i);
        gsap.to(tr, {
          x: -(distance() / (n - 1)) * i,
          duration: instant ? 0 : 0.7,
          ease: "power2.inOut",
          overwrite: true,
        });
      };
      const trigger = ScrollTrigger.create({
        trigger: el,
        start: "top top",
        end: "bottom bottom",
        invalidateOnRefresh: true,
        onRefreshInit: setDistance,
        onRefresh: (self) => {
          current = -1;
          show(Math.min(n - 1, Math.floor(self.progress * n)), true);
        },
        onUpdate: (self) => show(Math.min(n - 1, Math.floor(self.progress * n))),
      });
      ScrollTrigger.refresh();
      return () => {
        trigger.kill();
        gsap.set(tr, { clearProps: "transform" });
        el.removeAttribute("data-track");
        el.style.removeProperty("--process-distance");
      };
    });
    mm.add("(max-width: 767px), (prefers-reduced-motion: reduce)", () => {
      const onScroll = () => setActive(Math.round(ch.scrollLeft / Math.max(1, ch.clientWidth)));
      ch.addEventListener("scroll", onScroll, { passive: true });
      return () => ch.removeEventListener("scroll", onScroll);
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
                <li key={s.title} className="process__step card" aria-label={`Step ${i + 1} of ${STEPS.length}`}>
                  <div className="process__text">
                    <span className="t-caption">
                      Step {i + 1} / {STEPS.length}
                    </span>
                    <h3 className="process__name">{s.title}</h3>
                    <p className="t-lead process__copy">{s.copy}</p>
                  </div>
                  <StepVisual kind={s.visual} />
                </li>
              ))}
            </ol>
          </div>
          <div className="process__foot">
            <ol className="process__dots" aria-hidden="true">
              {STEPS.map((s, i) => (
                <li key={s.title} className={i === active ? "is-on" : undefined} />
              ))}
            </ol>
            <Button href="/login">Try it on one draft</Button>
          </div>
        </div>
      </div>
    </section>
  );
}
