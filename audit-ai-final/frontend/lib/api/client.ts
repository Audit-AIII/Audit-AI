"use client";

import { getSession, signOut } from "@/lib/session";
import type {
  ApprovalEventOut,
  BrandOut,
  BrandRules,
  BrandRulesOut,
  BrandSourceOut,
  CreateReviewBody,
  ErrorBody,
  ErrorCode,
  FindingComment,
  FindingDecision,
  LocksOut,
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
        return "That action isn't allowed on this account.";
      case 404:
        return "We couldn't find that. It may not exist, or it belongs to another organisation.";
      case 405:
        // A wrong method on a known path: the server sends code NOT_FOUND with status 405.
        return "That action isn't available here. Please reload the page and try again.";
      case 409:
        // The backend's 409 messages are safe and specific (stale version, a changed source, an
        // idempotency clash), so show them. "Still being processed" is retried before it gets here.
        return `This can’t be done right now: ${this.message}.`;
      case 422:
        if (/\bNUL\b|\\u0000|null character/i.test(this.message))
          return `Some text contains a hidden NUL character that can't be saved (${this.message}). Remove it and try again.`;
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

/* ---- Request rules from services/api/API.md "Conventions" and POST /api/reviews ---- */

/** Idempotency-Key: 1-200 visible ASCII characters (crypto.randomUUID() qualifies). */
export const isValidIdempotencyKey = (key: string) => /^[\x21-\x7E]{1,200}$/.test(key);

/** Path of the first string containing a NUL (\u0000), e.g. "body.text", or null. The server
 * rejects these with 422 because PostgreSQL cannot store them; catching it first gives a clearer
 * message and saves a round trip. */
export function findNulField(value: unknown, path = "body"): string | null {
  if (typeof value === "string") return value.includes("\u0000") ? path : null;
  if (Array.isArray(value)) {
    for (const [i, v] of value.entries()) {
      const hit = findNulField(v, `${path}.${i}`);
      if (hit) return hit;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const [k, v] of Object.entries(value)) {
      const hit = findNulField(v, `${path}.${k}`);
      if (hit) return hit;
    }
  }
  return null;
}
function findNulInForm(form: FormData): string | null {
  for (const [k, v] of form.entries()) if (typeof v === "string" && v.includes("\u0000")) return `body.${k}`;
  return null;
}

/** Checks done before any request leaves the browser; throws the same ApiError shape the server would. */
export function preflight(body: unknown, form: FormData | undefined, headers: Record<string, string>) {
  const key = headers["Idempotency-Key"];
  if (key !== undefined && !isValidIdempotencyKey(key))
    throw new ApiError(422, "VALIDATION_ERROR", "invalid request: header.Idempotency-Key", null);
  const nul = form ? findNulInForm(form) : findNulField(body);
  if (nul) throw new ApiError(422, "VALIDATION_ERROR", `invalid request: ${nul} contains a NUL character`, null);
}

/** 409 "still being processed": the same Idempotency-Key is already in flight on the server. */
/** The backend's own message for 409 / 422 (it says exactly what is wrong); plain text otherwise. */
export const backendMessage = (err: unknown) =>
  err instanceof ApiError ? (err.status === 409 || err.status === 422 ? err.message : err.userMessage) : "Something went wrong. Please try again.";

export const isStillProcessing = (err: unknown) =>
  err instanceof ApiError && err.status === 409 && /still being processed/i.test(err.message);

/**
 * Runs `send`; while the server answers 409 "still being processed" for this Idempotency-Key,
 * waits and sends the SAME request again (same key), so the user never sees it as an error. After
 * the last attempt the 409 is returned as a normal error.
 */
export async function retryWhileInFlight<T>(hasKey: boolean, send: () => Promise<T>, waitsMs = [1500, 3000, 5000, 8000, 12000]): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await send();
    } catch (err) {
      if (!hasKey || !isStillProcessing(err) || attempt >= waitsMs.length) throw err;
      await new Promise((r) => setTimeout(r, waitsMs[attempt]));
    }
  }
}

/**
 * Reads (GET) give up after this long, so an API that accepts the connection but never answers
 * shows the usual "couldn't reach the server" error instead of loading forever. Writes get no limit:
 * some are long by design (POST /api/evaluations runs for 1-4 minutes, reviews, uploads).
 */
export const READ_TIMEOUT_MS = 10_000;
export const readTimeout = (method: string) =>
  method === "GET" && typeof AbortSignal.timeout === "function" ? AbortSignal.timeout(READ_TIMEOUT_MS) : undefined;

type Options = {
  method?: "GET" | "POST" | "PUT";
  body?: unknown;
  /** Multipart body. Sent as-is with NO Content-Type: the browser adds it with the boundary. */
  form?: FormData;
  auth?: boolean;
  headers?: Record<string, string>;
};

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const headers = options.headers ?? {};
  preflight(options.body, options.form, headers);
  return retryWhileInFlight("Idempotency-Key" in headers, () => send<T>(path, options));
}

async function send<T>(path: string, { method = "GET", body, form, auth = true, headers = {} }: Options = {}): Promise<T> {
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
      signal: readTimeout(method),
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
  /** GET /api/brands/{id}/rules -> {brand_id, rules | null}. */
  brandRules: (brandId: string) => request<BrandRulesOut>(`/api/brands/${encodeURIComponent(brandId)}/rules`),
  /** PUT the whole rule set, or null to remove it. rule_set_id / version are set by the server and stripped here. */
  saveBrandRules: (brandId: string, rules: BrandRules | null) => {
    let body: BrandRules | null = null;
    if (rules) {
      const { rule_set_id: _id, version: _v, ...rest } = rules;
      void _id;
      void _v;
      body = rest;
    }
    return request<BrandRulesOut>(`/api/brands/${encodeURIComponent(brandId)}/rules`, { method: "PUT", body: { rules: body } });
  },
  review: (reviewId: string) => request<ReviewOut>(`/api/reviews/${encodeURIComponent(reviewId)}`),
  /** Approves the content version's latest review. 409 when stale, not decidable, a cited source
   * changed, or the caller's role doesn't match required_reviewer_role (message says which). */
  approve: (contentVersionId: string) =>
    request<ApprovalEventOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/approve`, { method: "POST" }),
  /** Dismiss / restore one finding (reversible; never changes the finding or the review). 409 = already
   * dismissed / not dismissed. */
  dismissFinding: (findingId: string, note?: string) =>
    request<FindingDecision>(`/api/findings/${encodeURIComponent(findingId)}/dismiss`, { method: "POST", body: note ? { note } : {} }),
  restoreFinding: (findingId: string) => request<FindingDecision>(`/api/findings/${encodeURIComponent(findingId)}/restore`, { method: "POST", body: {} }),
  findingComments: (findingId: string) => request<FindingComment[]>(`/api/findings/${encodeURIComponent(findingId)}/comments`),
  addFindingComment: (findingId: string, body: string) =>
    request<FindingComment>(`/api/findings/${encodeURIComponent(findingId)}/comments`, { method: "POST", body: { body } }),
  getLocks: (contentVersionId: string) => request<LocksOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/locks`),
  /** Replaces the whole list (server dedupes; invalid -> 422 with the reason). */
  putLocks: (contentVersionId: string, lockedPhrases: string[]) =>
    request<LocksOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/locks`, {
      method: "PUT",
      body: { locked_phrases: lockedPhrases },
    }),
  requestChanges: (contentVersionId: string, body: RequestChangesBody) =>
    request<ApprovalEventOut>(`/api/content-versions/${encodeURIComponent(contentVersionId)}/request-changes`, {
      method: "POST",
      body,
    }),
};
