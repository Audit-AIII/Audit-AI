"use client";

import type { AuditHistoryOut, WorkflowActionOut, WorkspaceAuditOut } from "@/lib/api/types";
import { request } from "./http";

/**
 * Workflow actions and audit history (services/api routers/content.py, content_versions.py,
 * workspace.py). Each action answers the draft's new workflow state; re-fetch the review afterwards
 * for its new allowed_actions.
 */
const item = (id: string) => `/api/content/${encodeURIComponent(id)}`;
const page = (limit: number, cursor?: string | null) =>
  `limit=${limit}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;

export const submitDraft = (contentItemId: string, contentVersionId: string) =>
  request<WorkflowActionOut>(`${item(contentItemId)}/submit`, { method: "POST", body: { content_version_id: contentVersionId } });

/** reviewerUserId null unassigns. */
export const assignReviewer = (contentItemId: string, reviewerUserId: string | null) =>
  request<WorkflowActionOut>(`${item(contentItemId)}/assign`, { method: "POST", body: { reviewer_user_id: reviewerUserId } });

export const markReviewed = (contentItemId: string, contentVersionId: string, note?: string) =>
  request<WorkflowActionOut>(`${item(contentItemId)}/mark-reviewed`, {
    method: "POST",
    body: { content_version_id: contentVersionId, ...(note ? { note } : {}) },
  });

export const publishVersion = (contentVersionId: string) =>
  request<WorkflowActionOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/publish`, { method: "POST" });

export const contentAudit = (contentItemId: string, cursor?: string | null, limit = 20) =>
  request<AuditHistoryOut>(`${item(contentItemId)}/audit?${page(limit, cursor)}`);

/** Owners only: anyone else gets a 403. */
export const workspaceAudit = (cursor?: string | null, limit = 20) =>
  request<WorkspaceAuditOut>(`/api/workspace/audit?${page(limit, cursor)}`);
