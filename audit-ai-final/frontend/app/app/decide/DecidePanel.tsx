"use client";

import { useState } from "react";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { isStub, isStubReview, verdict } from "@/components/app/reviewLabels";
import { canApprove, canReview, isDecidable, roleName } from "@/components/app/roles";
import { useReview, useReviewId } from "@/components/app/useReview";
import { ApiError, api } from "@/lib/api/client";
import type { ApprovalEventOut, ReviewOut } from "@/lib/api/types";
import { useSession } from "@/lib/session";
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
      </div>
    </>
  );
}

function Decide({ review, onDecided }: { review: ReviewOut; onDecided: () => void }) {
  const session = useSession();
  const role = session?.role ?? "";
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<null | "approve" | "changes_requested" | "rejected">(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ApprovalEventOut | null>(null);
  const [stubAck, setStubAck] = useState(false);

  const stub = isStubReview(review);
  const decidable = isDecidable(review.status);
  const required = review.required_reviewer_role;
  // Admin bypasses routing (approval_rules). The server re-checks everything.
  const routingBlocks = !!required && role !== "admin" && role !== required;
  const open = review.findings.filter((f) => !isStub(f) && f.verification_status !== "supported");
  const fixes = review.findings.filter((f) => f.suggested_correction);

  const approveBlock = !decidable
    ? null // the outcome banner explains
    : !canApprove(role)
      ? `Your role (${roleName(role)}) can’t approve. An approver needs to do this.`
      : routingBlocks
        ? `This review needs a ${roleName(required!)} (or an admin) to approve it.`
        : stub && !stubAck
          ? "Tick the box above first: nothing was really checked."
          : null;
  const changesBlock = !decidable ? null : !canReview(role) ? `Your role (${roleName(role)}) can’t send it back. A reviewer needs to do this.` : null;

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
                const v = verdict(f.verification_status);
                return (
                  <li key={f.finding_id} className="rows__item">
                    <div>
                      <p className="rows__title">“{f.original_text}”</p>
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
                  <del>{f.original_text}</del> <ins>{f.suggested_correction}</ins>
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
            <span className="field__label">Note for the writer (optional)</span>
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
            <button type="button" className="decision" onClick={() => decide("changes_requested")} disabled={!decidable || !!done || !!busy || !!changesBlock}>
              {busy === "changes_requested" ? "Sending…" : "Send back for changes"}
            </button>
            <button type="button" className="decision" onClick={() => decide("rejected")} disabled={!decidable || !!done || !!busy || !!changesBlock}>
              {busy === "rejected" ? "Rejecting…" : "Reject"}
            </button>
            {changesBlock && decidable && !done && <p className="t-caption decide__why">{changesBlock}</p>}
          </div>
        </Panel>

        <Panel n="03" label="Who approves" title="Approval rules">
          <dl className="spec">
            <div className="spec__row">
              <dt>You are</dt>
              <dd>{roleName(role)}</dd>
            </div>
            <div className="spec__row">
              <dt>Must be approved by</dt>
              <dd>{required ? `${roleName(required)} (or admin)` : "Any approver"}</dd>
            </div>
            <div className="spec__row">
              <dt>Why</dt>
              <dd>{required === "legal_reviewer" ? "A high-risk problem was found." : required === "brand_manager" ? "No high-risk problems were found." : "–"}</dd>
            </div>
            <div className="spec__row">
              <dt>Send back / reject</dt>
              <dd>Any reviewer or approver</dd>
            </div>
          </dl>
        </Panel>
      </Panels>
    </>
  );
}
