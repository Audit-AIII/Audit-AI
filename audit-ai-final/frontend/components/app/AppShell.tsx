"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { AccountNav } from "@/components/layout/AccountNav";
import { isOwner } from "@/lib/additions/governance";
import { ApiError, api } from "@/lib/api/client";
import { getSession, signIn, useSession } from "@/lib/session";
import { isSandTransitioning } from "@/lib/sandWave";
import { STAGES } from "./stages";
import { AppAmbient } from "./AppAmbient";
import { StageTrack, WorkspaceMenu, type WorkspacePage } from "./WorkspaceNav";

/** Workspace pages outside the five review stages (the "Workspace" menu in the bar). */
const WORKSPACE: WorkspacePage[] = [
  { href: "/app/insights", label: "Dashboard", hint: "Your brand at a glance: what gets flagged and how reviews move." },
  { href: "/app/queue", label: "Queue", hint: "Reviews waiting for a decision. Open one to decide on it." },
  { href: "/app/guidelines", label: "Guidelines", hint: "Upload, update or withdraw the documents drafts are checked against." },
  { href: "/app/rules", label: "Rules", hint: "Words to use or avoid, required disclaimers and accessibility settings for this brand." },
  { href: "/app/scorecard", label: "Scorecard", hint: "How well the checker does on a benchmark test set." },
  { href: "/app/team", label: "Team", hint: "Who is in this workspace, and inviting someone new." },
];
/** Owners only, on the server too; hidden so nobody else follows a link to a refusal. */
const AUDIT_PAGE: WorkspacePage = { href: "/app/audit", label: "Audit log", hint: "Who joined this workspace and whose role changed." };
/** Exact segment match, so /app/review-edit does not light up the "Review" stage. */
const inSection = (pathname: string, base: string) => pathname === base || pathname.startsWith(`${base}/`);

/**
 * Workspace frame: wordmark · stage track · Workspace menu · account (one row),
 * then the stage page, then a one-line status bar. Signed-out visitors are sent to sign in.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();
  const current = STAGES.find((s) => inSection(pathname, `/app/${s.slug}`));
  const pages = isOwner(session?.role) ? [...WORKSPACE, AUDIT_PAGE] : WORKSPACE;
  const page = pages.find((w) => inSection(pathname, w.href));

  const [offline, setOffline] = useState(false);

  useEffect(() => {
    // Not while a sand transition runs: signing out navigates to "/" under the sand.
    // Remember where they were going, so signing in returns there.
    if (!getSession() && !isSandTransitioning())
      router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);
  }, [session, router]);

  // Re-check the stored session with the server once per visit (a membership can be deactivated
  // between visits). 401 is handled centrally in the API client (signs out, back to /login).
  const token = session?.token;
  useEffect(() => {
    if (!token) return;
    let live = true;
    api
      .me()
      .then((me) => {
        const s = getSession();
        if (!live || !s) return;
        if (me.role !== s.role || me.organisation.id !== s.organisation.id || me.user.email !== s.email || (me.workspace && !s.workspace)) {
          signIn({ ...s, email: me.user.email, name: me.user.display_name ?? undefined, organisation: me.organisation, role: me.role, workspace: me.workspace ?? s.workspace });
        }
        setOffline(false);
      })
      .catch((err) => {
        if (live && err instanceof ApiError && err.status === 0) setOffline(true);
      });
    return () => {
      live = false;
    };
  }, [token]);

  if (!session) return null;

  return (
    <div className="app">
      <header className="app__bar board">
        <Link className="app__brand t-wordmark grain-text" data-text="Audit AI." href="/">
          Audit AI.
        </Link>
        <StageTrack current={current?.slug} />
        <WorkspaceMenu pages={pages} current={page} />
        <div className="app__account">
          <AccountNav inApp />
        </div>
      </header>

      <main id="main" className="app__main" tabIndex={-1}>
        <AppAmbient />
        {children}
      </main>

      <footer className="app__status board" aria-live="polite">
        <span className="app__status-dot" aria-hidden="true" />
        <p>
          {offline ? "Can’t reach the Audit AI server. Check that it is running." : (current?.hint ?? page?.hint ?? "Use the stages above to check a draft, or the Workspace menu for everything else.")}
        </p>
        <span className="t-caption app__status-sample">{session.organisation.name}</span>
      </footer>
    </div>
  );
}
