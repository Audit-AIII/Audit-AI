"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Button } from "@/components/primitives/Button";
import { TextLink } from "@/components/primitives/TextLink";

gsap.registerPlugin(ScrollTrigger);

const len = (word: string) => ({ "--len": word.length }) as CSSProperties;

function RaisedLine({ word }: { word: string }) {
  return (
    <span className="hero__line hero__line--raised">
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

  return (
    <section ref={section} id="top" className="hero" aria-labelledby="hero-title">
      <div ref={flap} className="hero__flap board">
        <div className="hero__light" aria-hidden="true" />
        <div className="hero__inner">
          <h1 id="hero-title" className="hero__title">
            <RaisedLine word="Check" /> <RaisedLine word="first." /> <PressedLine word="Publish" />{" "}
            <PressedLine word="sure." />
          </h1>
          <div className="hero__aside">
            <p className="t-lead">
              Audit AI reviews every draft against your approved guidelines, facts and assets before it goes live.
              Each finding shows its source, and a person makes the final call.
            </p>
            <div className="hero__actions">
              <Button href="#contact">Start a review</Button>
              <TextLink href="#findings">See a sample finding</TextLink>
            </div>
          </div>
        </div>
        <div ref={wash} className="hero__wash" aria-hidden="true" />
      </div>
    </section>
  );
}
