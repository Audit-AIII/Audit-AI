"use client";

import Link from "next/link";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { STAGES } from "./stages";

export type WorkspacePage = { href: string; label: string; hint: string };

/**
 * The five review stages as one pressed track (a groove cut into the bar). The current stage is a
 * raised paper tile that slides along the groove to wherever you are; the other stages sit flat in
 * the groove and press in a pixel on hover. Off a stage page the tile is hidden.
 */
export function StageTrack({ current }: { current: string | undefined }) {
  const list = useRef<HTMLOListElement>(null); // tile offsets are measured against .track (position: relative)
  const [tile, setTile] = useState<{ x: number; w: number } | null>(null);

  useLayoutEffect(() => {
    const place = () => {
      const el = list.current?.querySelector<HTMLElement>('[aria-current="page"]');
      setTile(el ? { x: el.offsetLeft, w: el.offsetWidth } : null);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [current]);

  return (
    <nav className="track" aria-label="Review stages">
      {tile && <span className="track__tile" aria-hidden="true" style={{ translate: `${tile.x}px 0`, width: tile.w }} />}
      <ol ref={list} className="track__list">
        {STAGES.map((s) => (
          <li key={s.slug}>
            <Link className="track__stage" href={`/app/${s.slug}`} aria-current={s.slug === current ? "page" : undefined}>
              <span className="track__n">{s.n}</span>
              <span className="track__label">{s.label}</span>
            </Link>
          </li>
        ))}
      </ol>
    </nav>
  );
}

/** Workspace pages outside the stages, behind one small button instead of a second row of links. */
export function WorkspaceMenu({ pages, current }: { pages: WorkspacePage[]; current: WorkspacePage | undefined }) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="wsmenu" ref={root}>
      <button
        ref={button}
        type="button"
        className="wsmenu__btn"
        aria-expanded={open}
        aria-controls={menuId}
        onClick={() => setOpen((v) => !v)}
      >
        <svg className="wsmenu__icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
          <rect x="2.5" y="2.5" width="6" height="6" rx="1.2" />
          <rect x="11.5" y="2.5" width="6" height="6" rx="1.2" />
          <rect x="2.5" y="11.5" width="6" height="6" rx="1.2" />
          <rect x="11.5" y="11.5" width="6" height="6" rx="1.2" />
        </svg>
        <span className="wsmenu__label">{current ? current.label : "Workspace"}</span>
        <span className="wsmenu__caret" aria-hidden="true">
          ▾
        </span>
      </button>
      <div id={menuId} className={`wsmenu__panel card${open ? " is-open" : ""}`}>
        <p className="t-caption wsmenu__title">Workspace</p>
        <ul className="wsmenu__list">
          {pages.map((p) => (
            <li key={p.href}>
              <Link
                className="wsmenu__item"
                href={p.href}
                aria-current={current?.href === p.href ? "page" : undefined}
                onClick={() => setOpen(false)}
                tabIndex={open ? undefined : -1}
              >
                <span className="wsmenu__item-label">{p.label}</span>
                <span className="wsmenu__item-hint">{p.hint}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
