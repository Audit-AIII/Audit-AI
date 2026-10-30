// Checked by `npx tsc --noEmit`, never run: the contract examples must fit the frontend's types.
import type {
  AuditHistoryOut,
  InvitationCreatedOut,
  InvitationsOut,
  LoginResponse,
  MembersOut,
  ReviewOut,
} from "../../lib/api/types";
import auditHistory from "../fixtures/governance/governance_audit_history.json";
import invitationCreated from "../fixtures/governance/governance_invitation_created.json";
import invitations from "../fixtures/governance/governance_invitations_list.json";
import inviteAccept from "../fixtures/governance/governance_invite_accept.json";
import members from "../fixtures/governance/governance_members.json";
import personal from "../fixtures/governance/governance_review_item_personal.json";
import approver from "../fixtures/governance/governance_review_item_team_approver.json";
import writer from "../fixtures/governance/governance_review_item_team_writer.json";

type Governance = Pick<
  ReviewOut,
  "workspace" | "author" | "owner" | "assigned_reviewer" | "workflow_status" | "risk_level" | "routing_reason" | "approval_mode" | "allowed_actions" | "summary_counts" | "is_current_version"
>;

export const checks: [Governance, Governance, Governance, AuditHistoryOut, MembersOut, InvitationCreatedOut, InvitationsOut, Omit<LoginResponse, "token_type">] = [
  personal,
  approver,
  writer,
  auditHistory,
  members,
  invitationCreated,
  invitations,
  inviteAccept,
];
