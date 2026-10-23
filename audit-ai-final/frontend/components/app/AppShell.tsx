"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { AccountNav } from "@/components/layout/AccountNav";
import { ApiError, api } from "@/lib/api/client";
import { getSession, signIn, useSession } from "@/lib/session";
import { isSandTransitioning } from "@/lib/sandWave";
import { STAGES } from "./stages";

/**
 * Workspace frame: wordmark · numbered stage bar (same on every stage page) · account,
 * then the stage page, then a one-line status bar. Signed-out visitors are sent to sign in.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();
  const current = STAGES.find((s) => pathname.startsWith(`/app/${s.slug}`));

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
        if (me.role !== s.role || me.organisation.id !== s.organisation.id || me.user.email !== s.email) {
          signIn({ ...s, email: me.user.email, name: me.user.display_name ?? undefined, organisation: me.organisation, role: me.role });
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
        <nav className="stages" aria-label="Review stages">
          <ol className="stages__list">
            {STAGES.map((s) => {
              const on = s.slug === current?.slug;
              return (
                <li key={s.slug}>
                  <Link className="stage" href={`/app/${s.slug}`} aria-current={on ? "page" : undefined}>
                    <span className="stage__n">{s.n}</span>
                    <span className="stage__label">{s.label}</span>
                  </Link>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="app__account">
          <AccountNav inApp />
        </div>
      </header>

      <main id="main" className="app__main" tabIndex={-1}>
        {children}
      </main>

      <footer className="app__status board" aria-live="polite">
        <span className="app__status-dot" aria-hidden="true" />
        <p>
          {offline ? "Can’t reach the Audit AI server. Check that it is running." : (current?.hint ?? "Pick a stage to begin.")}
        </p>
        <span className="t-caption app__status-sample">{session.organisation.name} · {session.role.replace(/_/g, " ")}</span>
      </footer>
    </div>
  );
}
