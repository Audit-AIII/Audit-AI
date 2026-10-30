"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/primitives/Button";
import { actionErrorText, isOwner, roleLook } from "@/lib/additions/governance";
import { listWorkspaces, switchWorkspace } from "@/lib/additions/workspace";
import { ApiError } from "@/lib/api/client";
import type { WorkspaceMembershipOut } from "@/lib/api/types";
import { clearWorkspaceMemory } from "@/lib/workspace";
import { sessionFrom, signIn, signOut, useSession } from "@/lib/session";
import { sandNavigate } from "@/lib/sandWave";

/** Extra workspace pages for the account menu's "More" group (single-user: shown to every owner). */
const MORE: { href: string; label: string }[] = [
  { href: "/app/queue", label: "Review queue" },
  { href: "/app/guidelines", label: "Guidelines" },
  { href: "/app/rules", label: "Brand rules" },
  { href: "/app/insights", label: "Insights" },
  { href: "/app/scorecard", label: "Trust Scorecard" },
  { href: "/app/team", label: "Team" },
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
  const [workspaces, setWorkspaces] = useState<WorkspaceMembershipOut[]>([]);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState<string | null>(null);
  const token = session?.token;

  // Read when the menu opens, so the landing page makes no extra call for people who never open it.
  useEffect(() => {
    if (!open || !token) return;
    let live = true;
    listWorkspaces()
      .then((list) => live && setWorkspaces(list))
      .catch(() => live && setWorkspaces([])); // no switcher; nothing else depends on it
    return () => {
      live = false;
    };
  }, [open, token]);

  const switchTo = async (id: string) => {
    setSwitching(true);
    setSwitchError(null);
    try {
      const res = await switchWorkspace(id);
      clearWorkspaceMemory();
      signIn(sessionFrom(res));
      // A full page load, so nothing in memory from the previous workspace survives.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/app");
    } catch (err) {
      // The current workspace stays as it was.
      setSwitchError(err instanceof ApiError ? actionErrorText(err, err.userMessage) : "Something went wrong. Please try again.");
      setSwitching(false);
    }
  };

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
          {workspaces.length > 1 && (
            <nav aria-label="Switch workspace" style={{ display: "grid", gap: 6, marginBottom: 6 }}>
              <p className="t-caption account__menu-label">Workspace</p>
              {workspaces.map((w) =>
                w.is_current ? (
                  <p key={w.workspace.id} className="account__menu-email" aria-current="true">
                    <span aria-hidden="true">✓ </span>
                    {w.workspace.name} · {roleLook(w.role).label}
                  </p>
                ) : (
                  <button key={w.workspace.id} type="button" className="link link--tap" style={{ textAlign: "left" }} disabled={switching} onClick={() => switchTo(w.workspace.id)}>
                    {w.workspace.name} · {roleLook(w.role).label}
                  </button>
                ),
              )}
              {switchError && (
                <p className="t-caption" role="alert" style={{ textTransform: "none", letterSpacing: 0 }}>
                  {switchError}
                </p>
              )}
            </nav>
          )}
          {(
            <nav aria-label="More pages" style={{ display: "grid", gap: 6, marginBottom: 6 }}>
              <p className="t-caption account__menu-label">More</p>
              {(isOwner(session.role) ? [...MORE, { href: "/app/audit", label: "Audit log" }] : MORE).map((m) => (
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
