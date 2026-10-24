"use client";

import { useId, useState } from "react";
import { api, backendMessage } from "@/lib/api/client";
import type { FindingDecision, FindingOut } from "@/lib/api/types";
import { codePoints, DISMISSED, noteProblem, TEXT_MAX } from "@/lib/additions/findingState";

/**
 * Dismiss / Restore one finding (POST /api/findings/{id}/dismiss | restore). Reversible, so no confirm
 * dialog. The UI changes only from the 201 response; on an error the old state stays and the
 * backend's message is shown as-is (e.g. 409 "this finding is already dismissed").
 * Dismissing never changes the verdict, evidence, suggestion, review status or approval guards.
 */
export function FindingDismiss({ f, onDecided }: { f: FindingOut; onDecided: (d: FindingDecision) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const noteId = useId();
  const tooLong = noteProblem(note);

  async function act(kind: "dismiss" | "restore") {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const d = kind === "dismiss" ? await api.dismissFinding(f.finding_id, note.trim() ? note : undefined) : await api.restoreFinding(f.finding_id);
      setNote("");
      onDecided(d);
    } catch (err) {
      setError(backendMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="add-dismiss" aria-label="Dismiss this finding">
      {f.dismissal ? (
        <>
          <p className="t-body panel__note">
            <span className="chip chip--dismissed">
              <span aria-hidden="true">{DISMISSED.glyph}</span> {DISMISSED.label}
            </span>{" "}
            Dismissed by you on {new Date(f.dismissal.at).toLocaleString()}.
          </p>
          {f.dismissal.note && <p className="t-body panel__note add-prewrap">Note: {f.dismissal.note}</p>}
          <p className="t-caption">The finding itself is unchanged. Dismissing doesn’t approve the draft.</p>
          <button type="button" className="add-btn-small" onClick={() => act("restore")} disabled={busy} aria-busy={busy}>
            {busy ? "Restoring…" : "Restore"}
          </button>
        </>
      ) : (
        <>
          <label className="t-caption" htmlFor={noteId}>
            Note (optional)
          </label>
          <textarea
            id={noteId}
            className="add-textarea"
            rows={2}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            aria-describedby={`${noteId}-count`}
            disabled={busy}
          />
          <span id={`${noteId}-count`} className="t-caption add-muted">
            {codePoints(note)} / {TEXT_MAX}
            {tooLong ? ` · ${tooLong}` : ""}
          </span>
          <button type="button" className="add-btn-small" onClick={() => act("dismiss")} disabled={busy || !!tooLong} aria-busy={busy}>
            {busy ? "Dismissing…" : "Dismiss this finding"}
          </button>
        </>
      )}
      {error && (
        <p className="app-alert app-alert--bad" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
