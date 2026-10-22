import type { Metadata } from "next";
import Link from "next/link";
import { Workspace } from "./Workspace";

export const metadata: Metadata = { title: "Workspace — Audit AI" };

export default function AppPage() {
  return (
    <main id="main" className="auth" tabIndex={-1}>
      <Link className="auth__brand t-wordmark" href="/">
        Audit AI.
      </Link>
      <Workspace />
    </main>
  );
}
