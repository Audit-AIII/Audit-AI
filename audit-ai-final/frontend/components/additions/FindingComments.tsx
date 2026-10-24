"use client";

import { useEffect, useId, useState } from "react";
import { EmptyState, ErrorState, LoadingState } from "@/components/additions/States";
import { api, backendMessage } from "@/lib/api/client";
import type { FindingComment } from "@/lib/api/types";
import { codePoints, commentProblem, TEXT_MAX } from "@/lib/additions/findingState";

type Load = { state: "loading" } | { state: "ok"; comments: FindingComment[] } | { state: "error"; error: unknown };

/**
 * Comments on one finding (GET / POST /api/findings/{id}/comments), oldest first. Single-user account:
 * the author is always "You". Bodies are plain text, rendered by React (escaped, never HTML), with
 * line breaks kept by white-space: pre-wrap. A comment appears only after the 201 response.
 */
export function FindingComments({ findingId, onAdded }: { findingId: string; onAdded: (c: FindingComment) => void }) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [tick, setTick] = useState(0);
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const boxId = useId();

  useEffect(() => {
    let live = true;
    api
      .findingComments(findingId)
      .then((comments) => live && setLoad({ state: "ok", comments }))
      .catch((err) => live && setLoad({ state: "error", error: err }));
    return () => {
      live = false;
    };
  }, [findingId, tick]);

  const problem = commentProblem(body);
  async function send() {
    if (sending || problem) return;
    setSending(true);
    setError(null);
    try {
      const c = await api.addFindingComment(findingId, body);
      setLoad((l) => (l.state === "ok" ? { state: "ok", comments: [...l.comments, c] } : l));
      setBody("");
      setAnnounce(`Comment added at ${new Date(c.created_at).toLocaleTimeString()}.`);
      onAdded(c);
    } catch (err) {
      setError(backendMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="add-comments" aria-labelledby={`${boxId}-title`}>
      <h3 id={`${boxId}-title`} className="t-caption">
        Comments
      </h3>
      <p className="t-caption add-muted">Only you can see these.</p>
      {load.state === "loading" && <LoadingState label="Loading comments…" />}
      {load.state === "error" && <ErrorState error={load.error} onRetry={() => setTick((t) => t + 1)} />}
      {load.state === "ok" &&
        (load.comments.length === 0 ? (
          <EmptyState title="No comments yet" />
        ) : (
          <ol className="add-comment-list" aria-label="Comments, oldest first">
            {load.comments.map((c) => (
              <li key={c.id} className="add-comment">
                <p className="add-comment__meta t-caption">
                  You · <time dateTime={c.created_at}>{new Date(c.created_at).toLocaleString()}</time>
                </p>
                <p className="add-comment__body add-prewrap">{c.body}</p>
              </li>
            ))}
          </ol>
        ))}
      <p className="add-sr" role="status" aria-live="polite">
        {announce}
      </p>
      {load.state === "ok" && (
        <>
          <label className="t-caption" htmlFor={boxId}>
            Add a comment
          </label>
          <textarea
            id={boxId}
            className="add-textarea"
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            disabled={sending}
            aria-describedby={`${boxId}-count`}
          />
          <span id={`${boxId}-count`} className="t-caption add-muted">
            {codePoints(body)} / {TEXT_MAX}
            {body && problem ? ` · ${problem}` : ""}
          </span>
          <button type="button" className="add-btn-small" onClick={send} disabled={sending || !!problem} aria-busy={sending}>
            {sending ? "Adding…" : "Add comment"}
          </button>
          {error && (
            <p className="app-alert app-alert--bad" role="alert">
              {error}
            </p>
          )}
        </>
      )}
    </section>
  );
}
