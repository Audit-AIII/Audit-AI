"use client";

import { AuditTimeline } from "@/components/additions/AuditTimeline";
import { Panel, Panels, StageHead } from "@/components/app/Stage";
import { workspaceAudit } from "@/lib/additions/workflow";

const fetchPage = (cursor: string | null) => workspaceAudit(cursor);

/** Workspace audit log: who joined, who was invited, whose role changed. Owners only, on the server. */
export function AuditLog() {
  return (
    <>
      <StageHead title="Audit log" />
      <Panels cols="wide">
        <Panel n="01" label="Workspace activity" title="Who changed what">
          <p className="t-body panel__note">Every change to this workspace’s members is kept here, and entries can’t be edited.</p>
          <AuditTimeline
            fetchPage={fetchPage}
            emptyTitle="Nothing recorded yet"
            emptyBody="Invitations and role changes will appear here."
            forbidden="Only workspace owners can see this."
          />
        </Panel>
      </Panels>
    </>
  );
}
