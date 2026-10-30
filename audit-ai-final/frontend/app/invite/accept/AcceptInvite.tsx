"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import "@/styles/additions.css";
import { Button } from "@/components/primitives/Button";
import { actionErrorText, roleLook } from "@/lib/additions/governance";
import { acceptInvitation } from "@/lib/additions/workspace";
import { ApiError } from "@/lib/api/client";
import type { LoginResponse } from "@/lib/api/types";
import { sessionFrom, signIn, signOut, useSession } from "@/lib/session";
import { clearWorkspaceMemory } from "@/lib/workspace";

/**
 * Accept an invitation (POST /api/invitations/accept needs a signed-in user). Accepting is always a
 * click, never automatic: opening a link shouldn't change which workspace someone is in. The token
 * stays in the URL only; it is never logged or stored.
 */
export function AcceptInvite() {
  const token = useSearchParams().get("token");
  const session = useSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [joined, setJoined] = useState<LoginResponse | null>(null);

  const accept = async () => {
    if (!token || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await acceptInvitation(token);
      // The new session is for another workspace, so nothing from the old one may carry over.
      clearWorkspaceMemory();
      signIn(sessionFrom(res));
      setJoined(res);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  if (joined) {
    const name = joined.workspace?.name ?? joined.organisation.name;
    return (
      <Card title="You’re in">
        <p className="t-body auth__switch">
          You joined <b>{name}</b> as <b>{roleLook(joined.role).label}</b>.
        </p>
        {/* A full page load, so nothing in memory from the previous workspace survives. */}
        {/* eslint-disable-next-line @next/next/no-location-assign-relative-destination */}
        <Button type="button" onClick={() => window.location.assign("/app")}>
          Open the workspace →
        </Button>
      </Card>
    );
  }

  if (!token)
    return (
      <Card title="Invitation">
        <p className="auth__alert auth__alert--bad" role="alert">
          This link is incomplete. Ask the person who invited you to send it again.
        </p>
      </Card>
    );

  if (!session) {
    const back = encodeURIComponent(`/invite/accept?token=${token}`);
    return (
      <Card title="You’re invited">
        <p className="t-body auth__switch">Someone invited you to their Audit AI workspace. Sign in or create an account with the email address the invitation was sent to.</p>
        <Button href={`/login?next=${back}`}>Sign in</Button>
        <p className="t-body auth__switch">
          New to Audit AI?{" "}
          <a className="link link--tap" href={`/login?mode=signup&next=${back}`}>
            Create an account
          </a>
        </p>
      </Card>
    );
  }

  const api = error instanceof ApiError ? error : null;
  const wrongPerson = api?.code === "INVITE_EMAIL_MISMATCH";
  // A dead invitation can't be retried; only a failure on the way there can.
  const dead = !!api && ["INVITE_EXPIRED", "INVITE_REVOKED", "INVITE_ALREADY_USED", "NOT_FOUND"].includes(api.code);

  return (
    <Card title="You’re invited">
      <p className="t-body auth__switch">
        Join this workspace as <b>{session.email}</b>? You can switch back to your own workspace at any time.
      </p>
      {!!error && (
        <p className="auth__alert auth__alert--bad" role="alert">
          {api ? actionErrorText(api, api.userMessage) : "Something went wrong. Please try again."}
          {api?.requestId && <span className="add-action-ref"> Reference {api.requestId}</span>}
        </p>
      )}
      {!wrongPerson && !dead && (
        <Button type="button" onClick={accept} disabled={busy} aria-busy={busy}>
          {busy ? "Joining…" : "Accept invitation"}
        </Button>
      )}
      {wrongPerson && (
        <Button
          type="button"
          onClick={() => {
            setError(null);
            signOut();
          }}
        >
          Sign out and use that email
        </Button>
      )}
      {dead && (
        <a className="link link--tap" href="/app">
          Go to my workspace
        </a>
      )}
    </Card>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="auth__card card" aria-labelledby="auth-title">
      <h1 id="auth-title" className="auth__title relief-pressed grain-text" data-text={title}>
        {title}
      </h1>
      {children}
    </section>
  );
}
