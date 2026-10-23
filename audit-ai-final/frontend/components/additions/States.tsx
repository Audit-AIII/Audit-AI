"use client";

import type { ReactNode } from "react";
import { Button } from "@/components/primitives/Button";
import { ApiError } from "@/lib/api/client";

/** Shared states for the additive pages. Status is always words plus a glyph, never colour alone. */

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="add-state add-state--empty" role="status">
      <span className="add-state__glyph" aria-hidden="true">○</span>
      <p className="add-state__title">{title}</p>
      {children && <div className="add-state__body">{children}</div>}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="add-state add-state--loading" role="status">
      <span className="add-state__spinner" aria-hidden="true" />
      {label}
    </p>
  );
}

/** Error with retry. Picks wording for network, permission, missing and server failures. */
export function ErrorState({ error, message, onRetry }: { error?: unknown; message?: string; onRetry?: () => void }) {
  const status = error instanceof ApiError ? error.status : null;
  const kind = status === 0 ? "network" : status === 403 ? "permission" : status === 404 ? "missing" : "error";
  const title = { network: "Can’t reach the server", permission: "You don’t have access", missing: "Not found", error: "Something went wrong" }[kind];
  const text = message ?? (error instanceof ApiError ? error.userMessage : "Please try again.");
  return (
    <div className="add-state add-state--error" role="alert">
      <span className="add-state__glyph" aria-hidden="true">{kind === "permission" ? "⊘" : "≠"}</span>
      <p className="add-state__title">{title}</p>
      <p className="add-state__body">{text}</p>
      {error instanceof ApiError && error.requestId && (
        <details className="add-details">
          <summary>Details</summary>
          <code className="add-mono">Reference {error.requestId}</code>
        </details>
      )}
      {onRetry && kind !== "permission" && (
        <Button type="button" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** "Sample data" label, reusing the existing placeholder alert as-is. */
export function SampleNotice({ children }: { children: ReactNode }) {
  return (
    <div className="app-alert app-alert--placeholder" role="note">
      <b>Sample data.</b> {children}
    </div>
  );
}

/** Small line for something the backend doesn't provide yet. */
export function NeedsBackend({ children }: { children: ReactNode }) {
  return (
    <p className="add-needs" role="note">
      <span aria-hidden="true">◌ </span>
      <b>Needs backend:</b> {children}
    </p>
  );
}
