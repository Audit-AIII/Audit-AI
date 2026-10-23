import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in — Audit AI" };

export default function LoginPage() {
  return (
    <main id="main" className="auth" tabIndex={-1}>
      <Link className="auth__brand t-wordmark" href="/">
        Audit AI.
      </Link>
      <Suspense>
        <LoginForm />
      </Suspense>
      <p className="t-body auth__note">
        Create an account with any email to try Audit AI with your own brand.
      </p>
    </main>
  );
}
