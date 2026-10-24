"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { findingChip, isStub, isStubReview, isWholeDraft, suggestionFor } from "@/components/app/reviewLabels";
import { isDecidable } from "@/components/app/roles";
import { useReview, useReviewId } from "@/components/app/useReview";
import { history, itemIdOf } from "@/lib/additions/content";
import { ApiError, api } from "@/lib/api/client";
import type { ApprovalEventOut, ReviewOut } from "@/lib/api/types";
import { saveDecision } from "@/lib/workspace";

const NOTE_MAX = 2000; // backend limit for request-changes notes

const OUTCOME: Record<string, string> = {
  approved: "Approved",
  changes_requested: "Changes requested",
  rejected: "Rejected",
};

/** Decide stage: approve, request changes or reject the review's content version. */
export function DecidePanel() {
  const id = useReviewId();
  return <DecideLoader key={id ?? "none"} id={id} />;
}

function DecideLoader({ id }: { id: string | null }) {
  const { load, reload } = useReview(id);
  if (load.state === "none") return <Empty title="No review chosen" body="Check a draft first, then come back here to decide on it." />;
  if (load.state === "loading")
    return (
      <>
        <StageHead title="Decide" status="Loading…" />
        <p className="t-body" role="status">
          Loading the review…
        </p>
      </>
    );
  if (load.state === "error") return <Empty title="Couldn’t load" body={load.message} bad />;
  return <Decide review={load.review} onDecided={reload} />;
}

function Empty({ title, body, bad = false }: { title: string; body: string; bad?: boolean }) {
  return (
    <>
      <StageHead title="Decide" status={title} />
      <div className="app-empty card">
        <p className={bad ? "app-alert app-alert--bad" : "t-body"} role={bad ? "alert" : undefined}>
          {body}
        </p>
        <Button href="/app/draft">Check a draft →</Button>
        <a className="link" href="/app/queue">Open the review queue →</a>
      </div>
    </>
  );
}

function Decide({ review, onDecided }: { review: ReviewOut; onDecided: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<null | "approve" | "changes_requested" | "rejected">(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ApprovalEventOut | null>(null);
  const [stubAck, setStubAck] = useState(false);
  // Newer version of the same content item than the one decided here? The backend refuses to
  // approve a stale version (409); say so up front. Unknown (no item id / history failed) = no warning.
  const [newerVersion, setNewerVersion] = useState<number | null>(null);
  const itemId = itemIdOf(review);
  useEffect(() => {
    if (!itemId || review.version_number == null) return;
    let live = true;
    history(itemId)
      .then((h) => {
        const cur = h.versions.find((v) => v.is_current);
        if (live && cur && cur.version_number > review.version_number!) setNewerVersion(cur.version_number);
      })
      .catch(() => {
        /* only drives the warning; the server still enforces staleness */
      });
    return () => {
      live = false;
    };
  }, [itemId, review.version_number]);

  const stub = isStubReview(review);
  const decidable = isDecidable(review.status);
  const open = review.findings.filter((f) => !isStub(f) && f.verification_status !== "supported");
  const fixes = review.findings.filter((f) => suggestionFor(f) !== null);

  const approveBlock = !decidable
    ? null // the outcome banner explains
    : newerVersion !== null
      ? "A newer version of this draft exists, so this one can’t be approved."
      : stub && !stubAck
          ? "Tick the box above first: nothing was really checked."
          : null;

  const decide = async (kind: "approve" | "changes_requested" | "rejected") => {
    if (busy) return;
    setBusy(kind);
    setError(null);
    try {
      const event =
        kind === "approve"
          ? await api.approve(review.content_version_id)
          : await api.requestChanges(review.content_version_id, { decision: kind, ...(note.trim() ? { note: note.trim() } : {}) });
      saveDecision(review.id, {
        action: event.action,
        note: event.note,
        created_at: event.created_at,
        actor_user_id: event.actor_user_id,
        version_number: event.version_number,
      });
      setDone(event);
      onDecided(); // reload: review.status now carries the outcome
    } catch (err) {
      setError(err instanceof ApiError ? err.userMessage : "Something went wrong. Please try again.");
    } finally {
      setBusy(null);
    }
  };

  const outcome = OUTCOME[review.status];

  return (
    <>
      <StageHead title="Decide" status={outcome ?? (decidable ? "Waiting for you" : review.status.replace(/_/g, " "))} />

      {done && (
        <div className="app-alert app-alert--ok" role="status">
          <b>Saved: {OUTCOME[done.action] ?? done.action}.</b> It’s now part of this draft’s record.{" "}
          <a className="link" href={`/app/record?id=${review.id}`}>
            See the record
          </a>
        </div>
      )}
      {!done && outcome && (
        <div className="app-alert" role="status">
          <b>Already decided: {outcome}.</b> A decision can only be made once per review.{" "}
          <a className="link" href={`/app/record?id=${review.id}`}>
            See the record
          </a>
        </div>
      )}
      {!outcome && !decidable && (
        <div className="app-alert" role="status">
          This review can’t be decided on ({review.status.replace(/_/g, " ")}). {review.status === "failed" ? "Fix the problem and check the draft again." : ""}
        </div>
      )}
      {newerVersion !== null && decidable && (
        <div className="app-alert" role="alert">
          <b>⚠ A newer version of this draft exists. Approving this one will be refused.</b> This is version {review.version_number}; the
          latest is version {newerVersion}. You can still send this one back.
        </div>
      )}
      {stub && decidable && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Nothing was really checked.</b> The server has no AI service set up, so this review is a placeholder.
        </div>
      )}

      <Panels>
        <Panel n="01" label="What was found" title={open.length ? `${open.length} open problem${open.length === 1 ? "" : "s"}` : "No open problems"}>
          {open.length > 0 ? (
            <ul className="rows">
              {open.map((f) => {
                const v = findingChip(f);
                return (
                  <li key={f.finding_id} className="rows__item">
                    <div>
                      <p className="rows__title">{isWholeDraft(f) ? "About the whole draft" : `“${f.original_text}”`}</p>
                      <p className="rows__meta">
                        <span className={`chip chip--${v.tone}`}>
                          {v.glyph} {v.label}
                        </span>
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="t-body panel__note">{stub ? "No real checks ran, so there is nothing to list." : "Every claim matched your documents."}</p>
          )}
          {fixes.length > 0 && (
            <div className="fixes">
              <p className="t-caption">Suggested wording (not applied, you edit the draft yourself)</p>
              {fixes.map((f) => (
                <p key={f.finding_id} className="diff">
                  <del>{f.original_text}</del> <ins>{suggestionFor(f)?.text}</ins> <span className="t-caption">({suggestionFor(f)?.label})</span>
                </p>
              ))}
            </div>
          )}
          <a className="link" href={`/app/review?id=${review.id}`}>
            ← Back to the problems
          </a>
        </Panel>

        <Panel n="02" label="Your decision" title="What should happen?">
          <p className="t-body panel__note">Nothing is published or changed for you. Your choice is saved to the record.</p>
          {stub && decidable && (
            <label className="option">
              <input type="checkbox" className="tick tick--checkbox" checked={stubAck} onChange={(e) => setStubAck(e.target.checked)} />
              <span className="option__text">
                <span className="option__label">I understand no real check ran</span>
                <span className="option__help">Approving now means approving unchecked text.</span>
              </span>
            </label>
          )}
          <label className="field">
            <span className="field__label">Note (optional, saved with your decision)</span>
            <textarea
              className="field__input decide__note"
              value={note}
              maxLength={NOTE_MAX}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What should change, and why"
              disabled={!decidable || !!done}
            />
          </label>
          <p className="t-caption panel__hint">The note is saved with “Send back” or “Reject”. Approvals are saved without a note.</p>
          {error && (
            <p className="app-alert app-alert--bad" role="alert">
              {error}
            </p>
          )}
          <div className="decisions">
            <Button type="button" onClick={() => decide("approve")} disabled={!decidable || !!done || !!busy || !!approveBlock} aria-describedby="approve-why">
              {busy === "approve" ? "Approving…" : "Approve"}
            </Button>
            {approveBlock && decidable && !done && (
              <p id="approve-why" className="t-caption decide__why">
                {approveBlock}
              </p>
            )}
            <button type="button" className="decision" onClick={() => decide("changes_requested")} disabled={!decidable || !!done || !!busy}>
              {busy === "changes_requested" ? "Sending…" : "Send back for changes"}
            </button>
            <button type="button" className="decision" onClick={() => decide("rejected")} disabled={!decidable || !!done || !!busy}>
              {busy === "rejected" ? "Rejecting…" : "Reject"}
            </button>
          </div>
        </Panel>

        <Panel n="03" label="How this works" title="How this works">
          <dl className="spec">
            <div className="spec__row">
              <dt>Who decides</dt>
              <dd>You decide on your own content.</dd>
            </div>
            <div className="spec__row">
              <dt>Approve</dt>
              <dd>Saves this exact version as approved. A newer version needs its own decision.</dd>
            </div>
            <div className="spec__row">
              <dt>Send back</dt>
              <dd>Keeps your note with the decision, so you know what to fix.</dd>
            </div>
            <div className="spec__row">
              <dt>What changes</dt>
              <dd>Nothing is published or changed for you.</dd>
            </div>
          </dl>
        </Panel>
      </Panels>
    </>
  );
}
