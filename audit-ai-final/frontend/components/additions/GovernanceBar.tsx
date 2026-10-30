"use client";

import { RiskBadge, WorkflowBadge } from "@/components/additions/Badges";
import { NotProvided } from "@/components/additions/States";
import { routingText } from "@/lib/additions/governance";
import type { ReviewOut, UserRef } from "@/lib/api/types";

const Person = ({ user, absent }: { user?: UserRef | null; absent: string }) => (user ? <>{user.display_name}</> : <NotProvided>{absent}</NotProvided>);

/**
 * Who owns a draft, where it stands and why (docs/governance.md 9.1), all from the API. A personal
 * workspace has one person, so it shows only status, risk and reason.
 */
export function GovernanceBar({ review }: { review: ReviewOut }) {
  const personal = review.workspace?.is_personal ?? true;
  const solo = review.approval_mode === "self";
  const reason = review.routing_reason ? routingText(review.routing_reason.text, solo) : null;
  return (
    <section className="add-gov card" aria-label="Where this draft stands">
      <dl className="add-gov__list">
        <div>
          <dt className="t-caption">Status</dt>
          <dd>
            <WorkflowBadge status={review.workflow_status} />
          </dd>
        </div>
        <div>
          <dt className="t-caption">Risk</dt>
          <dd>
            <RiskBadge level={review.risk_level} />
          </dd>
        </div>
        {!personal && (
          <>
            <div>
              <dt className="t-caption">Author</dt>
              <dd>
                <Person user={review.author} absent="Not provided" />
              </dd>
            </div>
            <div>
              <dt className="t-caption">Owner</dt>
              <dd>
                <Person user={review.owner} absent="Not provided" />
              </dd>
            </div>
            <div>
              <dt className="t-caption">Assigned reviewer</dt>
              <dd>
                <Person user={review.assigned_reviewer} absent="Not assigned" />
              </dd>
            </div>
          </>
        )}
        <div className="add-gov__reason">
          <dt className="t-caption">{solo ? "Why it needs a look" : "Why this needs review"}</dt>
          <dd>{reason ?? <NotProvided>No reason given yet</NotProvided>}</dd>
        </div>
      </dl>
      {solo && <p className="t-caption add-gov__solo">Solo sign-off: you are the only member, so you decide.</p>}
    </section>
  );
}
