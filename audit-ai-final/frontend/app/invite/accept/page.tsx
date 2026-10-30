import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { AcceptInvite } from "./AcceptInvite";

export const metadata: Metadata = { title: "Accept invitation — Audit AI", robots: { index: false } };

export default function AcceptInvitePage() {
  return (
    <main id="main" className="auth" tabIndex={-1}>
      <Link className="auth__brand t-wordmark" href="/">
        Audit AI.
      </Link>
      <Suspense fallback={<section className="auth__card auth__card--placeholder card" aria-hidden="true" />}>
        <AcceptInvite />
      </Suspense>
    </main>
  );
}
