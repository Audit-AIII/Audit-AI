"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { TextLink } from "@/components/primitives/TextLink";
import { StartReviewButton } from "@/components/layout/StartReview";

gsap.registerPlugin(ScrollTrigger);

const len = (word: string) => ({ "--len": word.length }) as CSSProperties;

function RaisedLine({ word }: { word: string }) {
  return (
    <span className="hero__line hero__line--raised sand-edge">
      <span className="hero__channel ply">
        <span className="hero__word relief-raised" style={len(word)}>
          {word}
        </span>
      </span>
    </span>
  );
}

function PressedLine({ word }: { word: string }) {
  return (
    <span className="hero__line hero__line--cut">
      <span className="hero__word relief-pressed grain-text" data-text={word} style={len(word)}>
        {word}
      </span>
    </span>
  );
}

/**
 * Hero board. On scroll the board stays put, sinks (scale) and darkens (wash)
 * while the next sheet slides over it. Light and sway pause while sinking.
 */
export function Hero() {
  const section = useRef<HTMLElement>(null);
  const flap = useRef<HTMLDivElement>(null);
  const wash = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const mm = gsap.matchMedia();
    mm.add("(prefers-reduced-motion: no-preference)", () => {
      gsap
        .timeline({
          scrollTrigger: {
            trigger: el,
            start: "top top",
            end: "bottom top",
            scrub: true,
            onUpdate: (self) => el.toggleAttribute("data-sinking", self.progress > 0.01),
          },
        })
        .to(flap.current, { y: () => el.offsetHeight, scale: 0.86, ease: "none" }, 0)
        .to(wash.current, { opacity: 0.42, ease: "none" }, 0);
    });
    return () => mm.revert();
  }, []);

  // Pointer-follow light: eased toward the cursor (fine pointers only, never with reduced motion).
  useEffect(() => {
    const el = section.current;
    if (!el) return;
    if (!window.matchMedia("(hover: hover) and (pointer: fine) and (prefers-reduced-motion: no-preference)").matches) return;

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
    const kick = () => {
      if (!frame) frame = requestAnimationFrame(step);
    };
    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      target.x = ((e.clientX - r.left) / r.width) * 2 - 1;
      target.y = ((e.clientY - r.top) / r.height) * 2 - 1;
      kick();
    };
    const onLeave = () => {
      target.x = 0;
      target.y = 0;
      kick();
    };
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      cancelAnimationFrame(frame);
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, []);

  return (
    <section ref={section} id="top" className="hero" aria-labelledby="hero-title">
      <div ref={flap} className="hero__flap board">
        <div className="hero__light-frame" aria-hidden="true">
          <div className="hero__light" />
        </div>
        <div className="hero__inner">
          <h1 id="hero-title" className="hero__title">
            <RaisedLine word="Check" /> <RaisedLine word="first." /> <PressedLine word="Publish" />{" "}
            <PressedLine word="sure." />
          </h1>
          <div className="hero__aside">
            <p className="t-lead">
              Audit AI checks every draft against your brand rules, approved facts and logos before it goes live. It
              shows why each problem was flagged, and a person always makes the final call.
            </p>
            <div className="hero__actions">
              <StartReviewButton />
              <TextLink href="#findings" arrow>
                See an example
              </TextLink>
            </div>
          </div>
        </div>
        <div ref={wash} className="hero__wash" aria-hidden="true" />
      </div>
    </section>
  );
}
