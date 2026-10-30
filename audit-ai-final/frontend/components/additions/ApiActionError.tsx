"use client";

import { ApiError } from "@/lib/api/client";
import { actionErrorText } from "@/lib/additions/governance";

/** Inline note for a refused or failed action. Sits next to the form, so what was typed stays. */
export function ApiActionError({ error }: { error: unknown }) {
  if (!error) return null;
  const api = error instanceof ApiError ? error : null;
  const text = api ? actionErrorText(api, api.userMessage) : "Something went wrong. Please try again.";
  return (
    <div className="app-alert app-alert--bad" role="alert">
      {text}
      {api?.requestId && <span className="add-action-ref"> Reference {api.requestId}</span>}
    </div>
  );
}
