"use client";

import { useEffect, useState } from "react";
import type {
  InvitationCreatedOut,
  InvitationOut,
  InvitationsOut,
  LoginResponse,
  MemberOut,
  MembersOut,
  WorkspaceMembershipOut,
} from "@/lib/api/types";
import { request } from "./http";

/** Members, invitations and switching workspace (services/api routers/workspace.py). */
const member = (userId: string) => `/api/workspace/members/${encodeURIComponent(userId)}`;

export const listMembers = () => request<MembersOut>("/api/workspace/members");
export const changeMemberRole = (userId: string, role: string) => request<MemberOut>(member(userId), { method: "PATCH", body: { role } });
export const removeMember = (userId: string) => request<MemberOut>(member(userId), { method: "DELETE" });

export const listInvitations = () => request<InvitationsOut>("/api/workspace/invitations");
/** The answer holds the token, shown once. Keep it in memory only. */
export const createInvitation = (email: string, role: string) =>
  request<InvitationCreatedOut>("/api/workspace/invitations", { method: "POST", body: { email, role } });
export const revokeInvitation = (invitationId: string) =>
  request<InvitationOut>(`/api/workspace/invitations/${encodeURIComponent(invitationId)}/revoke`, { method: "POST" });
/** Needs a signed-in user. Answers a new session for the joined workspace. */
export const acceptInvitation = (token: string) => request<LoginResponse>("/api/invitations/accept", { method: "POST", body: { token } });

/** How many people are in this workspace, or null until known. A failure leaves it null. */
export function useMemberCount() {
  const [count, setCount] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    listMembers()
      .then((m) => live && setCount(m.members.length))
      .catch(() => {
        /* only picks wording and which details to show; the server still decides everything */
      });
    return () => {
      live = false;
    };
  }, []);
  return count;
}

export const listWorkspaces = () => request<WorkspaceMembershipOut[]>("/api/workspaces");
export const switchWorkspace = (workspaceId: string) =>
  request<LoginResponse>("/api/auth/switch-workspace", { method: "POST", body: { workspace_id: workspaceId } });
