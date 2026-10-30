/**
 * Where to go after signing in: ?next= when it is a workspace path or the invitation page (never
 * another site), else /app. Pure, so qa/unit can test it.
 */
export function safeNext(raw: string | null): string {
  if (!raw) return "/app";
  if (/^\/app(\/|\?|$)/.test(raw)) return raw;
  return /^\/invite\/accept(\?[^#\\]*)?$/.test(raw) ? raw : "/app";
}
