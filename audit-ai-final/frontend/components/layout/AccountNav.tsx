"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { canApprove, canManageSources, canReview } from "@/components/app/roles";
import { Button } from "@/components/primitives/Button";
import { signOut, useSession } from "@/lib/session";
import { sandNavigate } from "@/lib/sandWave";

/** Extra workspace pages for the account menu's "More" group, each shown only to roles that can use it. */
const MORE: { href: string; label: string; show: (role: string) => boolean }[] = [
  { href: "/app/queue", label: "Review queue", show: canReview },
  { href: "/app/guidelines", label: "Guidelines", show: canManageSources },
  { href: "/app/insights", label: "Insights", show: canApprove },
  { href: "/app/scorecard", label: "Trust Scorecard", show: () => true },
];

/**
 * Header account area. Signed out: Sign in + Sign up.
 * Signed in: the email (opens a small menu with Sign out) + Workspace button.
 */
export function AccountNav({ onNavigate, inApp = false }: { onNavigate?: () => void; inApp?: boolean }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session) {
    return (
      <div className="account">
        <Link className="link link--tap" href="/login" onClick={onNavigate}>
          Sign in
        </Link>
        <Button href="/login?mode=signup" className="nav__cta" onClick={onNavigate}>
          Sign up
        </Button>
      </div>
    );
  }

  return (
    <div className="account" ref={root}>
      <div className="account__menu-wrap">
        <button
          type="button"
          className="account__who"
          aria-expanded={open}
          aria-controls={menuId}
          title={session.email}
          onClick={() => setOpen((v) => !v)}
        >
          <span className="account__dot" aria-hidden="true" />
          <span className="sr-only">Signed in as </span>
          <span className="account__email">{session.email}</span>
          <span className="account__caret" aria-hidden="true">
            ▾
          </span>
        </button>
        <div id={menuId} className={`account__menu card${open ? " is-open" : ""}`}>
          <p className="t-caption account__menu-label">Signed in as</p>
          <p className="account__menu-email">{session.email}</p>
          {MORE.some((m) => m.show(session.role)) && (
            <nav aria-label="More pages" style={{ display: "grid", gap: 6, marginBottom: 6 }}>
              <p className="t-caption account__menu-label">More</p>
              {MORE.filter((m) => m.show(session.role)).map((m) => (
                <Link
                  key={m.href}
                  className="link link--tap"
                  href={m.href}
                  onClick={() => {
                    setOpen(false);
                    onNavigate?.();
                  }}
                >
                  {m.label}
                </Link>
              ))}
            </nav>
          )}
          <button
            type="button"
            className="link link--tap"
            onClick={() => {
              setOpen(false);
              onNavigate?.();
              // In the workspace: sign out under the sand wave, then land on the home page.
              if (inApp) sandNavigate("/", signOut);
              else signOut();
            }}
          >
            Sign out
          </button>
        </div>
      </div>
      {!inApp && (
        <Button href="/app" className="nav__cta" onClick={onNavigate}>
          Workspace
        </Button>
      )}
    </div>
  );
}
