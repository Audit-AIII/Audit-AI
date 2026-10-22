"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { FormEvent } from "react";
import { Button } from "@/components/primitives/Button";
import { Field } from "@/components/primitives/Field";
import { signIn } from "@/lib/session";

/** Sign in / create account card. Mock auth: a valid form stores the email as the session and opens the workspace. */
export function LoginForm() {
  const router = useRouter();
  const signup = useSearchParams().get("mode") === "signup";

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget;
    if (!form.reportValidity()) return;
    const data = new FormData(form);
    const email = String(data.get("email") ?? "").trim();
    const name = String(data.get("name") ?? "").trim() || undefined;
    signIn({ email, name });
    router.push("/app");
  };

  return (
    <section className="auth__card card" aria-labelledby="auth-title">
      <h1 id="auth-title" className="auth__title relief-pressed grain-text" data-text={signup ? "Create account" : "Sign in"}>
        {signup ? "Create account" : "Sign in"}
      </h1>
      <form className="auth__form" onSubmit={onSubmit}>
        {signup && <Field label="Your name" id="a-name" name="name" autoComplete="name" required />}
        <Field label="Work email" id="a-email" name="email" type="email" autoComplete="email" required />
        <Field
          label="Password"
          id="a-password"
          name="password"
          type="password"
          autoComplete={signup ? "new-password" : "current-password"}
          minLength={6}
          required
        />
        <Button type="submit">{signup ? "Create account" : "Sign in"}</Button>
      </form>
      <p className="t-body auth__switch">
        {signup ? "Already have an account? " : "New to Audit AI? "}
        <a className="link link--tap" href={signup ? "/login" : "/login?mode=signup"}>
          {signup ? "Sign in" : "Create an account"}
        </a>
      </p>
    </section>
  );
}
