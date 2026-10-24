"use client";

import { API_URL, ApiError, preflight, retryWhileInFlight } from "@/lib/api/client";
import type { ErrorBody } from "@/lib/api/types";
import { getSession, signOut } from "@/lib/session";

/**
 * Local copy of lib/api/client.ts's private request() for the additive pages (that one is not
 * exported, and the original must not be edited). Same behaviour: one ApiError for every failure,
 * multipart bodies without a hand-set Content-Type, and a 401 on a signed-in call ends the session.
 */
type Options = {
  method?: "GET" | "POST";
  body?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
};

function isErrorBody(x: unknown): x is ErrorBody {
  const e = (x as ErrorBody | null)?.error;
  return !!e && typeof e.code === "string" && typeof e.message === "string";
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const headers = options.headers ?? {};
  preflight(options.body, options.form, headers);
  return retryWhileInFlight("Idempotency-Key" in headers, () => send<T>(path, options));
}

async function send<T>(path: string, { method = "GET", body, form, headers = {} }: Options = {}): Promise<T> {
  const token = getSession()?.token;
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
    /* non-JSON body, handled below */
  }
  if (!res.ok) {
    const err = isErrorBody(data)
      ? new ApiError(res.status, data.error.code, data.error.message, data.error.request_id ?? requestId)
      : new ApiError(res.status, res.status >= 500 ? "INTERNAL_ERROR" : "BAD_RESPONSE", res.statusText, requestId);
    if (res.status === 401 && token) {
      signOut();
      if (!window.location.pathname.startsWith("/login")) {
        // eslint-disable-next-line @next/next/no-location-assign-relative-destination
        window.location.assign("/login?expired=1");
      }
    }
    throw err;
  }
  if (data === null) throw new ApiError(res.status, "BAD_RESPONSE", "empty response", requestId);
  return data as T;
}

/** A route that isn't on the backend yet answers 404 (unknown path) or 405 (path taken by another method). */
export const isMissingRoute = (err: unknown) => err instanceof ApiError && (err.status === 404 || err.status === 405);

/** Plain-language message for any error; keeps the backend's own text for 409 and 422. */
export const errorText = (err: unknown, fallback = "Something went wrong. Please try again.") =>
  err instanceof ApiError ? err.userMessage : fallback;
