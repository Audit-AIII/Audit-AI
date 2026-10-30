"use client";

import { useEffect, useState } from "react";
// add- classes (Dismissed badge, buttons, states); this route has no AdditionsFrame.
import "@/styles/additions.css";
import { ApiActionError } from "@/components/additions/ApiActionError";
import { ConfirmDialog } from "@/components/additions/ConfirmDialog";
import { GovernanceBar } from "@/components/additions/GovernanceBar";
import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { findingChip, isStub, isStubReview, isWholeDraft, suggestionFor } from "@/components/app/reviewLabels";
import { isDecidable } from "@/components/app/roles";
import { useReview, useReviewId } from "@/components/app/useReview";
import { history, itemIdOf } from "@/lib/additions/content";
import { DISMISSED, isDismissed, openDismissed } from "@/lib/additions/findingState";
import { isAllowed, workflowLook } from "@/lib/additions/governance";
import { assignReviewer, markReviewed, publishVersion, submitDraft } from "@/lib/additions/workflow";
import { listMembers } from "@/lib/additions/workspace";
import { api } from "@/lib/api/client";
import type { ApprovalEventOut, MemberOut, ReviewOut } from "@/lib/api/types";
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
  const [busy, setBusy] = useState<null | "approve" | "changes_requested" | "rejected" | "workflow">(null);
  const [error, setError] = useState<unknown>(null);
  const [done, setDone] = useState<ApprovalEventOut | null>(null);
  // What a workflow action (submit, assign, mark reviewed, publish) just did. The status shown is the server's.
  const [moved, setMoved] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | "rejected" | "publish">(null);
  const [members, setMembers] = useState<MemberOut[] | null>(null);
  const [reviewer, setReviewer] = useState(review.assigned_reviewer?.id ?? "");
  const allowed = review.allowed_actions;
  const personal = review.workspace?.is_personal ?? true;
  const canAssign = !!allowed?.includes("assign");
  const [stubAck, setStubAck] = useState(false);
  // Newer version of the same content item than the one decided here? The backend refuses to
  // approve a stale version (409); say so up front. Unknown (no item id / history failed) = no warning.
  const [newerVersion, setNewerVersion] = useState<number | null>(null);
  const [newerReviewId, setNewerReviewId] = useState<string | null>(null);
  const itemId = itemIdOf(review);
  useEffect(() => {
    if (!canAssign) return;
    let live = true;
    listMembers()
      .then((m) => live && setMembers(m.members))
      .catch((err) => live && setError(err));
    return () => {
      live = false;
    };
  }, [canAssign]);
  useEffect(() => {
    if (!itemId || review.version_number == null) return;
    let live = true;
    history(itemId)
      .then((h) => {
        const cur = h.versions.find((v) => v.is_current);
        if (live && cur && cur.version_number > review.version_number!) {
          setNewerVersion(cur.version_number);
          const latest = [...cur.reviews].sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
          setNewerReviewId(latest?.id ?? null);
        }
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
  // Dismissed findings stay listed and counted; dismissing never unblocks a decision.
  const counts = openDismissed(open);

  const stale = newerVersion !== null || review.is_current_version === false;
  const approveBlock = !decidable
    ? null // the outcome banner explains
    : stale
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
      setError(err); // the note stays, so nothing typed is lost
    } finally {
      setBusy(null);
    }
  };

  /** Runs a workflow action, then reloads: the status shown is always the server's. */
  const act = async (word: string, run: () => Promise<{ workflow_status: string }>, after?: () => void) => {
    if (busy) return;
    setBusy("workflow");
    setError(null);
    setMoved(null);
    try {
      const out = await run();
      setMoved(`${word} Status: ${workflowLook(out.workflow_status).label}.`);
      after?.();
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };
  // Solo sign-off has no one to send a draft to: approving submits it (docs/governance.md D4).
  const submitAction = personal ? null : allowed?.includes("resubmit") ? "resubmit" : allowed?.includes("submit") ? "submit" : null;
  const canReview = !!allowed?.includes("mark_reviewed");
  const canPublish = !!allowed?.includes("publish");
  const canApproveNow = isAllowed(allowed, "approve");
  const canSendBack = isAllowed(allowed, "request_changes");
  const canReject = isAllowed(allowed, "reject");
  const noteApplies = canSendBack || canReject || canReview;
  const anyAction = canApproveNow || noteApplies || canPublish || canAssign || !!submitAction;

  const outcome = OUTCOME[review.status];

  return (
    <>
      <StageHead title="Decide" status={outcome ?? (decidable ? (personal ? "Waiting for you" : "Waiting for a decision") : review.status.replace(/_/g, " "))} />

      {review.workflow_status !== undefined && <GovernanceBar review={review} />}
      {moved && (
        <div className="app-alert app-alert--ok" role="status">
          <b>Saved.</b> {moved}{" "}
          <a className="link" href={`/app/record?id=${review.id}`}>
            See the record
          </a>
        </div>
      )}

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
      {stale && decidable && (
        <div className="app-alert" role="alert">
          <b>⚠ A newer version of this draft exists, so this one can’t be approved.</b>{" "}
          {newerVersion !== null && `This is version ${review.version_number}; the latest is version ${newerVersion}. `}
          {canSendBack && "You can still send this one back. "}
          {newerReviewId && (
            <a className="link" href={`/app/decide?id=${newerReviewId}`}>
              Open the latest version
            </a>
          )}
        </div>
      )}
      {stub && decidable && (
        <div className="app-alert app-alert--placeholder" role="note">
          <b>Nothing was really checked.</b> The server has no AI service set up, so this review is a placeholder.
        </div>
      )}

      <Panels>
        <Panel n="01" label="What was found" title={open.length ? `${open.length} problem${open.length === 1 ? "" : "s"}` : "No open problems"}>
          {open.length > 0 && (
            <p className="t-body panel__note">
              {counts.open} open, {counts.dismissed} dismissed
            </p>
          )}
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
                        {isDismissed(f) && (
                          <>
                            {" "}
                            <span className="chip add-dismissed">
                              <span aria-hidden="true">{DISMISSED.glyph}</span> {DISMISSED.label}
                            </span>
                          </>
                        )}
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
          <p className="t-body panel__note">{anyAction ? "Nothing is published or changed for you. Your choice is saved to the record." : "There’s nothing for you to do on this draft right now."}</p>
          {stub && decidable && (
            <label className="option">
              <input type="checkbox" className="tick tick--checkbox" checked={stubAck} onChange={(e) => setStubAck(e.target.checked)} />
              <span className="option__text">
                <span className="option__label">I understand no real check ran</span>
                <span className="option__help">Approving now means approving unchecked text.</span>
              </span>
            </label>
          )}
          {noteApplies && (
          <label className="field">
            <span className="field__label">Note (optional, saved with your decision)</span>
            <textarea
              className="field__input decide__note"
              value={note}
              maxLength={NOTE_MAX}
              onChange={(e) => setNote(e.target.value)}
              placeholder="What should change, and why"
              disabled={(!decidable && !canReview) || !!done}
            />
          </label>
          )}
          {noteApplies && <p className="t-caption panel__hint">The note is saved with {canReview ? "“Mark as reviewed”, " : ""}“Send back” or “Reject”. Approvals are saved without a note.</p>}
          <ApiActionError error={error} />
          <div className="decisions">
            {submitAction && itemId && (
              <Button type="button" onClick={() => act("Sent for review.", () => submitDraft(itemId, review.content_version_id))} disabled={!!busy}>
                {busy === "workflow" ? "Saving…" : submitAction === "resubmit" ? "Send for review again" : "Send for review"}
              </Button>
            )}
            {canReview && itemId && (
              <Button
                type="button"
                onClick={() => act("Marked as reviewed.", () => markReviewed(itemId, review.content_version_id, note.trim() || undefined), () => setNote(""))}
                disabled={!!busy}
              >
                {busy === "workflow" ? "Saving…" : "Mark as reviewed"}
              </Button>
            )}
            {canApproveNow && (
            <Button type="button" onClick={() => decide("approve")} disabled={!decidable || !!done || !!busy || !!approveBlock} aria-describedby="approve-why">
              {busy === "approve" ? "Approving…" : "Approve"}
            </Button>
            )}
            {canApproveNow && approveBlock && decidable && !done && (
              <p id="approve-why" className="t-caption decide__why">
                {approveBlock}
              </p>
            )}
            {canSendBack && (
            <button type="button" className="decision" onClick={() => decide("changes_requested")} disabled={!decidable || !!done || !!busy}>
              {busy === "changes_requested" ? "Sending…" : "Send back for changes"}
            </button>
            )}
            {canReject && (
            <button type="button" className="decision" onClick={() => setConfirm("rejected")} disabled={!decidable || !!done || !!busy}>
              {busy === "rejected" ? "Rejecting…" : "Reject"}
            </button>
            )}
            {canPublish && (
              <Button type="button" onClick={() => setConfirm("publish")} disabled={!!busy}>
                {busy === "workflow" ? "Saving…" : "Mark as published"}
              </Button>
            )}
          </div>
          {canAssign && itemId && (
            <div className="add-assign">
              <label className="add-field-row">
                <span className="t-caption">Assigned reviewer</span>
                <select className="add-select" value={reviewer} onChange={(e) => setReviewer(e.target.value)} disabled={!members || !!busy}>
                  <option value="">Nobody</option>
                  {members?.map((m) => (
                    <option key={m.user.id} value={m.user.id}>
                      {m.user.display_name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                className="add-btn-small"
                onClick={() => act(reviewer ? "Reviewer assigned." : "Reviewer removed.", () => assignReviewer(itemId, reviewer || null))}
                disabled={!members || !!busy || reviewer === (review.assigned_reviewer?.id ?? "")}
              >
                {reviewer || !review.assigned_reviewer ? "Assign" : "Unassign"}
              </button>
            </div>
          )}
          <ConfirmDialog
            open={confirm !== null}
            title={confirm === "publish" ? "Mark this version as published?" : "Reject this draft?"}
            confirmLabel={confirm === "publish" ? "Mark as published" : "Reject"}
            onCancel={() => setConfirm(null)}
            onConfirm={() => {
              const kind = confirm;
              setConfirm(null);
              if (kind === "rejected") decide("rejected");
              if (kind === "publish") act("Marked as published.", () => publishVersion(review.content_version_id));
            }}
          >
            <p>
              {confirm === "publish"
                ? "Audit AI doesn’t post anything for you. This records that this exact version went out."
                : "This is saved to the draft’s record, along with your note if you wrote one."}
            </p>
          </ConfirmDialog>
        </Panel>

        <Panel n="03" label="How this works" title="How this works">
          <dl className="spec">
            <div className="spec__row">
              <dt>Who decides</dt>
              <dd>{personal ? "You decide on your own content." : "Your role sets what you can do here. The author can’t approve their own draft while someone else can."}</dd>
            </div>
            <div className="spec__row">
              <dt>Approve</dt>
              <dd>Saves this exact version as approved. A newer version needs its own decision.</dd>
            </div>
            <div className="spec__row">
              <dt>Send back</dt>
              <dd>{personal ? "Keeps your note with the decision, so you know what to fix." : "Keeps your note with the decision, so the writer knows what to fix."}</dd>
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
