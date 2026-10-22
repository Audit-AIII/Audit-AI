"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { AccountNav } from "@/components/layout/AccountNav";
import { getSession, useSession } from "@/lib/session";
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

  useEffect(() => {
    if (!getSession()) router.replace("/login");
  }, [session, router]);

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
        <p>{current?.hint ?? "Pick a stage to begin."}</p>
        <span className="t-caption app__status-sample">Sample data</span>
      </footer>
    </div>
  );
}
