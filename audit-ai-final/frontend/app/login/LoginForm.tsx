"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Field } from "@/components/primitives/Field";
import { ApiError, api } from "@/lib/api/client";
import type { LoginResponse } from "@/lib/api/types";
import { rememberBrand } from "@/lib/brand";
import { getSession, signIn } from "@/lib/session";
import { sandNavigate } from "@/lib/sandWave";

const PASSWORD_MIN = 8;
const PASSWORD_MAX_BYTES = 72; // bcrypt limit on the backend
const bytes = (s: string) => new TextEncoder().encode(s).length;

/** Stores the session the same way for sign-in and sign-up. */
function startSession(res: LoginResponse) {
  signIn({
    email: res.user.email,
    name: res.user.display_name ?? undefined,
    token: res.access_token,
    userId: res.user.id,
    organisation: res.organisation,
    role: res.role,
  });
}

/** Where to go after signing in: ?next= when it is a workspace path (never another site), else /app. */
export function safeNext(raw: string | null): string {
  return raw && /^\/app(\/|\?|$)/.test(raw) ? raw : "/app";
}

const generic = (err: unknown) => (err instanceof ApiError ? err.userMessage : "Something went wrong. Please try again.");

/** Sign in (POST /api/auth/login) or, with ?mode=signup, create an account (POST /api/auth/register). */
export function LoginForm() {
  const params = useSearchParams();
  const signup = params.get("mode") === "signup";
  const next = safeNext(params.get("next"));
  const router = useRouter();
  // Already signed in when the page opens (e.g. an old bookmark to /login): don't ask again, go
  // where they were headed. Checked once on open only, so a sign-in made on this page isn't
  // redirected twice (that one moves on under the sand wave). Sign-up page is left alone.
  useEffect(() => {
    if (getSession() && !signup) router.replace(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- on open only
  }, []);
  return signup ? <SignUpForm /> : <SignInForm expired={params.get("expired") === "1"} next={next} />;
}

function SignInForm({ expired, next }: { expired: boolean; next: string }) {
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
      startSession(await api.login(String(data.get("email") ?? "").trim(), String(data.get("password") ?? "")));
      sandNavigate(next);
    } catch (err) {
      // 401 here means wrong email/password (deliberately not told apart by the backend).
      setError(err instanceof ApiError && err.status === 401 ? "That email and password don't match an account." : generic(err));
      setBusy(false);
    }
  };

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
      <form className="auth__form" onSubmit={onSubmit}>
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

function SignUpForm() {
  const [error, setError] = useState<string | null>(null);
  const [exists, setExists] = useState(false);
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    const password = String(data.get("password") ?? "");
    const confirm = form.elements.namedItem("confirm") as HTMLInputElement;
    // Custom checks shown through the browser's own validation bubble, like the built-in ones.
    confirm.setCustomValidity(password === String(data.get("confirm") ?? "") ? "" : "The passwords don't match.");
    const pw = form.elements.namedItem("password") as HTMLInputElement;
    pw.setCustomValidity(bytes(password) > PASSWORD_MAX_BYTES ? "That password is too long (72 bytes at most)." : "");
    if (!form.reportValidity() || busy) return;

    const opt = (k: string) => String(data.get(k) ?? "").trim() || undefined;
    setBusy(true);
    setError(null);
    setExists(false);
    try {
      const res = await api.register({
        email: String(data.get("email") ?? "").trim(),
        password,
        display_name: opt("name"),
        brand_name: opt("brand"),
      });
      startSession(res);
      if (res.brand?.id) rememberBrand(res.brand.id);
      sandNavigate("/");
    } catch (err) {
      setBusy(false);
      if (err instanceof ApiError && err.status === 409) {
        setExists(true);
        setError("An account with this email already exists. Sign in instead.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError(`Please check the form: ${err.message.replace(/^invalid request:\s*/, "")}.`);
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Too many sign-ups from here in a short time. Please wait a few minutes and try again.");
      } else {
        setError(generic(err));
      }
    }
  };

  return (
    <section className="auth__card card" aria-labelledby="auth-title">
      <h1 id="auth-title" className="auth__title relief-pressed grain-text" data-text="Create account">
        Create account
      </h1>
      <form className="auth__form" onSubmit={onSubmit}>
        <Field label="Your name (optional)" id="a-name" name="name" autoComplete="name" maxLength={200} />
        <Field label="Work email" id="a-email" name="email" type="email" autoComplete="email" required />
        <Field
          label="Password (8 characters or more)"
          id="a-password"
          name="password"
          type="password"
          autoComplete="new-password"
          minLength={PASSWORD_MIN}
          maxLength={PASSWORD_MAX_BYTES}
          required
          onInput={(e) => e.currentTarget.setCustomValidity("")}
        />
        <Field
          label="Confirm password"
          id="a-confirm"
          name="confirm"
          type="password"
          autoComplete="new-password"
          required
          onInput={(e) => e.currentTarget.setCustomValidity("")}
        />
        <Field label="Brand or product name (optional)" id="a-brand" name="brand" maxLength={200} placeholder="e.g. Lumen Bottle" />
        {error && (
          <p className="auth__alert auth__alert--bad" role="alert">
            {error}{" "}
            {exists && (
              <a className="link" href="/login">
                Go to sign in
              </a>
            )}
          </p>
        )}
        <Button type="submit" disabled={busy} aria-busy={busy}>
          {busy ? "Creating account…" : "Create account"}
        </Button>
      </form>
      <p className="t-body auth__switch">
        Already have an account?{" "}
        <a className="link link--tap" href="/login">
          Sign in
        </a>
      </p>
    </section>
  );
}
