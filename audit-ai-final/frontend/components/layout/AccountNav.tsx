"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/primitives/Button";
import { signOut, useSession } from "@/lib/session";

/**
 * Header account area. Signed out: Sign in + Sign up.
 * Signed in: the email (opens a small menu with Sign out) + Workspace button.
 */
export function AccountNav({ onNavigate, inApp = false }: { onNavigate?: () => void; inApp?: boolean }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const router = useRouter();

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
        <div id={menuId} className="account__menu card" hidden={!open}>
          <p className="t-caption account__menu-label">Signed in as</p>
          <p className="account__menu-email">{session.email}</p>
          <button
            type="button"
            className="link link--tap"
            onClick={() => {
              setOpen(false);
              signOut();
              onNavigate?.();
              if (inApp) router.push("/");
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
