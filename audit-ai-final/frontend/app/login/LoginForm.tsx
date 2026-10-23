"use client";

import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Field } from "@/components/primitives/Field";
import { ApiError, api } from "@/lib/api/client";
import { signIn } from "@/lib/session";
import { sandNavigate } from "@/lib/sandWave";

/**
 * Sign in against POST /api/auth/login. The backend has no sign-up route: accounts are created by
 * an admin (or scripts/seed.py for the demo), so "Create account" explains that instead of
 * pretending to make one.
 */
export function LoginForm() {
  const params = useSearchParams();
  const signup = params.get("mode") === "signup";
  const expired = params.get("expired") === "1";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    if (!form.reportValidity() || busy) return;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    try {
      const res = await api.login(String(data.get("email") ?? "").trim(), String(data.get("password") ?? ""));
      signIn({
        email: res.user.email,
        name: res.user.display_name ?? undefined,
        token: res.access_token,
        userId: res.user.id,
        organisation: res.organisation,
        role: res.role,
      });
      sandNavigate("/app");
    } catch (err) {
      // 401 here means wrong email/password (deliberately not told apart by the backend).
      setError(
        err instanceof ApiError && err.status === 401
          ? "That email and password don't match an account."
          : err instanceof ApiError
            ? err.userMessage
            : "Something went wrong. Please try again.",
      );
      setBusy(false);
    }
  };

  if (signup) {
    return (
      <section className="auth__card card" aria-labelledby="auth-title">
        <h1 id="auth-title" className="auth__title relief-pressed grain-text" data-text="Create account">
          Create account
        </h1>
        <p className="t-body auth__switch">
          Accounts are created by your organisation’s admin. Ask them to add you, then sign in here.
        </p>
        <p className="t-body auth__switch">
          <a className="link link--tap" href="/login">
            Back to sign in
          </a>
        </p>
      </section>
    );
  }

  return (
    <section className="auth__card card" aria-labelledby="auth-title">
      <h1 id="auth-title" className="auth__title relief-pressed grain-text" data-text="Sign in">
        Sign in
      </h1>
      {expired && !error && (
        <p className="auth__alert" role="status">
          Your session ended. Please sign in again.
        </p>
      )}
      <form className="auth__form" onSubmit={onSubmit} noValidate={false}>
        <Field label="Work email" id="a-email" name="email" type="email" autoComplete="email" required />
        <Field label="Password" id="a-password" name="password" type="password" autoComplete="current-password" required />
        {error && (
          <p className="auth__alert auth__alert--bad" role="alert">
            {error}
          </p>
        )}
        <Button type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>
      <p className="t-body auth__switch">
        New to Audit AI?{" "}
        <a className="link link--tap" href="/login?mode=signup">
          Create an account
        </a>
      </p>
    </section>
  );
}
