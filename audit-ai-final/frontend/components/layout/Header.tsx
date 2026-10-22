"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/primitives/Button";

export const NAV_LINKS = [
  { href: "#checks", label: "Checks" },
  { href: "#process", label: "Process" },
  { href: "#findings", label: "Findings" },
  { href: "#sources", label: "Sources" },
  { href: "#contact", label: "Contact" },
] as const;

/** Fixed 68px paper bar. Slides away on scroll-down, returns on scroll-up (500ms). Links collapse ≤767px. */
export function Header() {
  const [hidden, setHidden] = useState(false);
  const [open, setOpen] = useState(false);
  const lastY = useRef(0);
  const menuId = useId();

  useEffect(() => {
    const onScroll = () => {
      const y = window.scrollY;
      const delta = y - lastY.current;
      if (Math.abs(delta) > 4) {
        setHidden(delta > 0 && y > 120);
        lastY.current = y;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const close = () => setOpen(false);

  return (
    <header className="nav" data-hidden={hidden && !open ? "" : undefined} data-open={open ? "" : undefined}>
      <div className="nav__bar board">
        <a className="nav__brand t-wordmark" href="#top" onClick={close}>
          Audit AI.
        </a>
        <nav className="nav__menu" id={menuId} aria-label="Main">
          <ul className="nav__links">
            {NAV_LINKS.map((l) => (
              <li key={l.href}>
                <a className="link link--tap" href={l.href} onClick={close}>
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
          <Button href="#contact" className="nav__cta" onClick={close}>
            Start a review
          </Button>
        </nav>
        <button
          type="button"
          className="icon-btn nav__toggle"
          aria-expanded={open}
          aria-controls={menuId}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="icon-btn__glyph" aria-hidden="true" />
          <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
        </button>
      </div>
    </header>
  );
}
