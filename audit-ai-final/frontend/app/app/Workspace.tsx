"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { getSession, signOut, useSession } from "@/lib/session";

// Placeholder until the review workspace is built (prompts/02-app-later.md, DESIGN.md §17).
const NEXT = ["Send a draft", "See what needs fixing", "Approve and keep a record", "Your approved documents", "Source Watch", "Trust Scorecard"];

export function Workspace() {
  const session = useSession();
  const router = useRouter();
  // The session lives in the browser, so check storage after mount; signed-out visitors go to sign in.
  useEffect(() => {
    if (!getSession()) router.replace("/login");
  }, [session, router]);

  if (!session) return null;

  return (
    <section className="auth__card card" aria-labelledby="app-title">
      <h1 id="app-title" className="auth__title relief-pressed grain-text" data-text="Workspace">
        Workspace
      </h1>
      <p className="t-lead auth__who">
        Signed in as <b>{session.email}</b>
        {session.name ? ` (${session.name})` : ""}
      </p>
      <p className="t-body">The review workspace is being built next.</p>
      <ul className="auth__list">
        {NEXT.map((n) => (
          <li key={n} className="t-caption">
            {n}
          </li>
        ))}
      </ul>
      <div className="auth__row">
        <Link className="link link--tap" href="/">
          Back to the landing page
        </Link>
        <button
          type="button"
          className="link link--tap"
          onClick={() => {
            signOut();
            router.push("/");
          }}
        >
          Sign out
        </button>
      </div>
    </section>
  );
}
