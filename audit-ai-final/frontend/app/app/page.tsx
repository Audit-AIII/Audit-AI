import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Workspace — Audit AI" };

// Placeholder until the review workspace is built (prompts/02-app-later.md, DESIGN.md §17).
const NEXT = ["New submission", "Review with evidence", "Decide and record", "Library", "Source Watch", "Trust Scorecard"];

export default function AppPage() {
  return (
    <main id="main" className="auth" tabIndex={-1}>
      <Link className="auth__brand t-wordmark" href="/">
        Audit AI.
      </Link>
      <section className="auth__card card" aria-labelledby="app-title">
        <h1 id="app-title" className="auth__title relief-pressed grain-text" data-text="Workspace">
          Workspace
        </h1>
        <p className="t-lead">You are signed in. The review workspace is being built next.</p>
        <ul className="auth__list">
          {NEXT.map((n) => (
            <li key={n} className="t-caption">
              {n}
            </li>
          ))}
        </ul>
        <Link className="link link--tap" href="/">
          Back to the landing page
        </Link>
      </section>
    </main>
  );
}
