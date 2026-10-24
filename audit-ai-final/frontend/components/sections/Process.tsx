"use client";

import { useEffect, useRef, useState } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Heading } from "@/components/primitives/Heading";
import { StartReviewButton } from "@/components/layout/StartReview";

gsap.registerPlugin(ScrollTrigger);

// COPY TO REVIEW: step descriptions expand the §15 parentheticals into sentences.
const STEPS = [
  { title: "Add what's approved", copy: "Upload your brand guide and key facts as PDF, Word or text files. You only do this once.", visual: "import" },
  { title: "Send in your draft", copy: "Paste the text, or upload a PDF, Word or text file.", visual: "submit" },
  {
    title: "See what needs fixing",
    copy: "Each problem comes with the reason, the document it is based on and a suggested fix.",
    visual: "review",
  },
  { title: "Approve and keep a record", copy: "A person signs it off, and every decision is saved so you can show it later.", visual: "approve" },
] as const;

function StepVisual({ kind }: { kind: (typeof STEPS)[number]["visual"] }) {
  switch (kind) {
    case "import":
      return (
        <div className="pv pv--import">
          {["Brand guide", "Key facts", "Fact sheet"].map((t) => (
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
      // About two screens of scrolling per step.
      const setDistance = () => el.style.setProperty("--process-scroll", `${(n - 1) * 180}vh`);
      setDistance();
      let current = -1;
      const show = (i: number, instant = false) => {
        if (i === current) return;
        current = i;
        setActive(i);
        gsap.to(tr, {
          x: -(distance() / (n - 1)) * i,
          duration: instant ? 0 : 1.8,
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
        el.style.removeProperty("--process-scroll");
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
            Draft to approved in four steps
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
            <StartReviewButton>Try it on one draft</StartReviewButton>
          </div>
        </div>
      </div>
    </section>
  );
}
