"use client";

import type { BrandSourceOut } from "@/lib/api/types";
import { request } from "./http";

/**
 * Brand document calls for the Guidelines page. Paths and multipart field names copied from
 * services/api/src/inkloom_api/routers/brands.py:
 *   POST /api/brands/{id}/sources                      file, title, sensitivity, approve
 *   POST /api/brands/{id}/sources/{sid}/versions       file
 *   POST /api/brands/{id}/sources/{sid}/approve        (no body)
 *   POST /api/brands/{id}/sources/{sid}/withdraw       JSON {status: "superseded"|"archived", reason}
 *   DELETE /api/brands/{id}/sources/{sid}                -> {id, title, deleted: true}; never-approved only (else 409)
 * Upload/approve/withdraw/new version need manage_sources (source_manager, admin).
 */
export type FlippedDependent = { content_version_id: string; review_id: string };
export type WithdrawResult = { source: BrandSourceOut; reason: string; flipped: FlippedDependent[] };
export type NewVersionResult = { source: BrandSourceOut; version_number: number; flipped: FlippedDependent[] };
export type DeletedSource = { id: string; title: string; deleted: true };

const base = (brandId: string) => `/api/brands/${encodeURIComponent(brandId)}/sources`;

export const listSources = (brandId: string) => request<BrandSourceOut[]>(base(brandId));
/** Deletes a document that was never approved (draft). Approved / withdrawn ones are kept for the record (409). */
export const deleteSource = (brandId: string, sourceId: string) =>
  request<DeletedSource>(`${base(brandId)}/${encodeURIComponent(sourceId)}`, { method: "DELETE" });

export function uploadSource(brandId: string, file: File, opts: { title: string; confidential: boolean; approve: boolean }) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("title", opts.title);
  form.append("sensitivity", opts.confidential ? "confidential" : "normal");
  form.append("approve", opts.approve ? "true" : "false");
  return request<BrandSourceOut>(base(brandId), { method: "POST", form });
}

export function uploadSourceVersion(brandId: string, sourceId: string, file: File) {
  const form = new FormData();
  form.append("file", file, file.name);
  return request<NewVersionResult>(`${base(brandId)}/${encodeURIComponent(sourceId)}/versions`, { method: "POST", form });
}

export const approveSource = (brandId: string, sourceId: string) =>
  request<BrandSourceOut>(`${base(brandId)}/${encodeURIComponent(sourceId)}/approve`, { method: "POST" });

export const withdrawSource = (brandId: string, sourceId: string, body: { status: "superseded" | "archived"; reason: string }) =>
  request<WithdrawResult>(`${base(brandId)}/${encodeURIComponent(sourceId)}/withdraw`, { method: "POST", body });
