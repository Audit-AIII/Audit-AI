"use client";

import { getSession, signOut } from "@/lib/session";
import type {
  ApprovalEventOut,
  BrandOut,
  BrandSourceOut,
  CreateReviewBody,
  ErrorBody,
  ErrorCode,
  LoginResponse,
  RegisterBody,
  RegisterResponse,
  RequestChangesBody,
  ReviewOut,
  SessionInfo,
} from "./types";

/**
 * Typed client for the INKLOOM backend. The only frontend setting is the backend URL
 * (NEXT_PUBLIC_API_URL). Never put API keys or backend secrets in frontend env vars: anything
 * NEXT_PUBLIC_* is shipped to every browser.
 */
/** File types the backend can read, for <input accept>. Max size 10 MB. */
export const ACCEPTED_FILE_TYPES = ".pdf,.docx,.txt";
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");

/**
 * One error type for every failure, so screens handle errors in one way.
 * `status` 0 means the request never got a response (backend down, CORS, offline).
 */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ErrorCode | "NETWORK_ERROR" | "BAD_RESPONSE",
    message: string,
    readonly requestId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** Plain-language text for the screen. The backend message is kept for 422 (it names the field). */
  get userMessage(): string {
    switch (this.status) {
      case 0:
        return "We couldn't reach the Audit AI server. Check that it is running and try again.";
      case 401:
        return "Your session has ended. Please sign in again.";
      case 403:
        return "Your role doesn't allow this. Ask an admin for access.";
      case 404:
        return "We couldn't find that. It may not exist, or it belongs to another organisation.";
      case 409:
        // The backend's 409 messages are safe and specific (stale version, wrong approver role,
        // idempotency clash), so show them.
        return `This can’t be done right now: ${this.message}.`;
      case 422:
        return `Something in the form isn't valid (${this.message}).`;
      case 429:
        return "Too many checks in a short time. Please wait a minute and try again.";
      default:
        return "Something went wrong on the server. Please try again.";
    }
  }
}

function isErrorBody(x: unknown): x is ErrorBody {
  const e = (x as ErrorBody | null)?.error;
  return !!e && typeof e.code === "string" && typeof e.message === "string";
}

type Options = {
  method?: "GET" | "POST";
  body?: unknown;
  /** Multipart body. Sent as-is with NO Content-Type: the browser adds it with the boundary. */
  form?: FormData;
  auth?: boolean;
  headers?: Record<string, string>;
};

async function request<T>(path: string, { method = "GET", body, form, auth = true, headers = {} }: Options = {}): Promise<T> {
  const token = auth ? getSession()?.token : undefined;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined && !form ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "network error", null);
  }

  const requestId = res.headers.get("X-Request-ID");
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    // e.g. a proxy's HTML 502 page; handled below as a bad response
  }

  if (!res.ok) {
    const err = isErrorBody(data)
      ? new ApiError(res.status, data.error.code, data.error.message, data.error.request_id ?? requestId)
      : new ApiError(res.status, res.status >= 500 ? "INTERNAL_ERROR" : "BAD_RESPONSE", res.statusText, requestId);
    // Central 401: a token that stopped working (expired, membership deactivated) ends the
    // session everywhere. Login's own 401 (wrong password) is not a session ending.
    if (res.status === 401 && token) {
      signOut();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        // Full page load on purpose: drops all in-memory state from the ended session.
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign("/login?expired=1");
      }
    }
    if (process.env.NODE_ENV !== "production") console.warn(`[api] ${method} ${path} -> ${res.status} ${err.code}`, err.requestId);
    throw err;
  }
  if (data === null) throw new ApiError(res.status, "BAD_RESPONSE", "empty response", requestId);
  return data as T;
}

export const api = {
  login: (email: string, password: string) =>
    request<LoginResponse>("/api/auth/login", { method: "POST", body: { email, password }, auth: false }),
  register: (body: RegisterBody) => request<RegisterResponse>("/api/auth/register", { method: "POST", body, auth: false }),
  me: () => request<SessionInfo>("/api/auth/me"),
  brands: () => request<BrandOut[]>("/api/brands"),
  createBrand: (name: string, description?: string) =>
    request<BrandOut>("/api/brands", { method: "POST", body: { name, ...(description ? { description } : {}) } }),
  uploadBrandSource: (brandId: string, file: File, opts: { title: string; approve?: boolean; confidential?: boolean }) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("title", opts.title);
    form.append("sensitivity", opts.confidential ? "confidential" : "normal");
    form.append("approve", opts.approve ? "true" : "false");
    return request<BrandSourceOut>(`/api/brands/${encodeURIComponent(brandId)}/sources`, { method: "POST", form });
  },
  approveBrandSource: (brandId: string, sourceId: string) =>
    request<BrandSourceOut>(`/api/brands/${encodeURIComponent(brandId)}/sources/${encodeURIComponent(sourceId)}/approve`, {
      method: "POST",
    }),
  brandSources: (brandId: string) => request<BrandSourceOut[]>(`/api/brands/${encodeURIComponent(brandId)}/sources`),
  /** Sends an Idempotency-Key so a double click or retry replays the first review instead of running two. */
  createReview: (body: CreateReviewBody, idempotencyKey: string) =>
    request<ReviewOut>("/api/reviews", { method: "POST", body, headers: { "Idempotency-Key": idempotencyKey } }),
  /** Review a .pdf/.docx/.txt file; the backend extracts the text. 422 = unreadable/unsupported. */
  createReviewFromFile: (brandId: string, file: File, idempotencyKey: string, title?: string) => {
    const form = new FormData();
    form.append("brand_id", brandId);
    form.append("file", file, file.name);
    if (title) form.append("title", title);
    return request<ReviewOut>("/api/reviews/upload", { method: "POST", form, headers: { "Idempotency-Key": idempotencyKey } });
  },
  review: (reviewId: string) => request<ReviewOut>(`/api/reviews/${encodeURIComponent(reviewId)}`),
  /** Approves the content version's latest review. 409 when stale, not decidable, a cited source
   * changed, or the caller's role doesn't match required_reviewer_role (message says which). */
  approve: (contentVersionId: string) =>
    request<ApprovalEventOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/approve`, { method: "POST" }),
  requestChanges: (contentVersionId: string, body: RequestChangesBody) =>
    request<ApprovalEventOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/request-changes`, {
      method: "POST",
      body,
    }),
};
