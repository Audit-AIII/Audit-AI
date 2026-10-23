"use client";

import { Button } from "@/components/primitives/Button";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { isStub, isStubReview } from "@/components/app/reviewLabels";
import { roleName } from "@/components/app/roles";
import { useReview, useReviewId } from "@/components/app/useReview";
import type { ReviewOut } from "@/lib/api/types";
import { useSession } from "@/lib/session";
import { getDecision, type SavedDecision } from "@/lib/workspace";

const OUTCOME: Record<string, string> = {
  approved: "Approved",
  changes_requested: "Sent back for changes",
  rejected: "Rejected",
};

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "–";

/** Record stage: what happened to one review, from the server's own timestamps and status. */
export function RecordPanel() {
  const id = useReviewId();
  return <RecordLoader key={id ?? "none"} id={id} />;
}

function RecordLoader({ id }: { id: string | null }) {
  const { load } = useReview(id);
  if (load.state === "none" || load.state === "error") {
    return (
      <>
        <StageHead title="Record" status={load.state === "none" ? "No review chosen" : "Couldn’t load"} />
        <div className="app-empty card">
          <p className={load.state === "error" ? "app-alert app-alert--bad" : "t-body"} role={load.state === "error" ? "alert" : undefined}>
            {load.state === "error" ? load.message : "Check a draft first. Its record will show up here."}
          </p>
          <Button href="/app/draft">Check a draft →</Button>
        </div>
      </>
    );
  }
  if (load.state === "loading") {
    return (
      <>
        <StageHead title="Record" status="Loading…" />
        <p className="t-body" role="status">
          Loading the record…
        </p>
      </>
    );
  }
  // Client-only render (AppShell waits for the session), so localStorage is safe to read here.
  return <Record review={load.review} decision={getDecision(load.review.id)} />;
}

type Step = { at: string | null; who: string; what: string; local?: boolean };

function Record({ review, decision }: { review: ReviewOut; decision: SavedDecision | null }) {
  const session = useSession();
  const stub = isStubReview(review);
  const counted = review.findings.filter((f) => !isStub(f));
  const open = counted.filter((f) => f.verification_status !== "supported").length;
  const outcome = OUTCOME[review.status];
  // Only trust the browser's copy of the decision if it agrees with the server's outcome.
  const localDecision = decision && decision.action === review.status ? decision : null;
  const byYou = localDecision && session && localDecision.actor_user_id === session.userId;

  const steps: Step[] = [
    { at: review.created_at, who: "Writer", what: "Sent the draft for checking" },
    {
      at: review.completed_at ?? review.started_at,
      who: "Audit AI",
      what: stub
        ? "Ran a placeholder check (no AI service set up, nothing was really checked)"
        : review.status === "failed"
          ? `Couldn’t check the draft${review.error_summary ? `: ${review.error_summary}` : ""}`
          : `Checked the draft: ${counted.length} claim${counted.length === 1 ? "" : "s"}, ${open} to look at`,
    },
  ];
  if (outcome) {
    steps.push({
      at: localDecision?.created_at ?? review.updated_at,
      who: byYou ? "You" : "A reviewer",
      what: `${outcome}${localDecision?.note ? `: “${localDecision.note}”` : ""}`,
      local: !!localDecision,
    });
  } else if (review.status === "needs_human_review" || review.status === "completed") {
    steps.push({ at: null, who: "Waiting", what: "No decision yet" });
  }

  const e = review.engine;
  const passport = stub
    ? [{ step: "Claim check", service: "Nobody (placeholder)", note: "Your text wasn’t sent to any AI" }]
    : [
        {
          step: "Claim check",
          service: e?.provider ? `${e.provider}${e.model_id ? ` · ${e.model_id}` : ""}` : "Rules only",
          note: e?.provider ? "Outside AI service" : "Stayed on the server",
        },
      ];

  return (
    <>
      <StageHead title="Record" status={outcome ?? (stub ? "Placeholder result" : "Not decided yet")} />
      <Panels>
        <Panel n="01" label="What happened" title="Timeline">
          <ol className="timeline">
            {steps.map((t, i) => (
              <li key={i} className="timeline__item">
                <span className="timeline__at t-caption">{when(t.at)}</span>
                <div>
                  <p className="rows__title">{t.who}</p>
                  <p className="rows__meta">{t.what}</p>
                </div>
              </li>
            ))}
          </ol>
          {outcome && !localDecision && (
            <p className="t-caption panel__hint">The decision’s note and exact time were made in another browser, so only the outcome is shown.</p>
          )}
        </Panel>

        <Panel n="02" label="Data Passport" title="Who read your text">
          <ul className="rows">
            {passport.map((r) => (
              <li key={r.step} className="rows__item">
                <div>
                  <p className="rows__title">{r.step}</p>
                  <p className="rows__meta">{r.service}</p>
                </div>
                <span className="tag">{r.note}</span>
              </li>
            ))}
          </ul>
          {review.served_from_cache && <p className="t-caption panel__hint">This result reused an earlier identical check, so no new AI call was made.</p>}
        </Panel>

        <Panel n="03" label="Details" title="For your files">
          <dl className="spec">
            <div className="spec__row">
              <dt>Review</dt>
              <dd>
                <code className="request-id">{review.id}</code>
              </dd>
            </div>
            <div className="spec__row">
              <dt>Approver needed</dt>
              <dd>{review.required_reviewer_role ? roleName(review.required_reviewer_role) : "–"}</dd>
            </div>
            <div className="spec__row">
              <dt>Checks version</dt>
              <dd>{e?.contract_version ?? "–"}</dd>
            </div>
          </dl>
          <button type="button" className="decision" disabled>
            Download as PDF · coming soon
          </button>
          <a className="link" href={`/app/review?id=${review.id}`}>
            ← Back to the problems
          </a>
        </Panel>
      </Panels>
    </>
  );
}
