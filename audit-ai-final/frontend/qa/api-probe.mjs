// Calls the REAL backend and compares every response's fields with lib/api/types.ts.
// Usage: AUDIT_EMAIL=admin@seed.inkloom.demo AUDIT_PASSWORD=... AUDIT_BRAND_ID=... node qa/api-probe.mjs
// (credentials come from the environment; never commit them)
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, AUDIT_BRAND_ID: brand } = process.env;
if (!email || !password || !brand) throw new Error("set AUDIT_EMAIL, AUDIT_PASSWORD, AUDIT_BRAND_ID");

// Field lists the frontend expects (mirror of lib/api/types.ts)
const EXPECT = {
  login: ["access_token", "token_type", "user", "organisation", "role"],
  me: ["user", "organisation", "role"],
  user: ["id", "email", "display_name"],
  organisation: ["id", "name", "slug"],
  source: ["id", "brand_profile_id", "title", "status", "sensitivity", "source_type", "latest_version", "created_at", "updated_at"],
  review: ["id", "content_version_id", "status", "report_status", "engine", "error_summary", "served_from_cache", "started_at", "completed_at", "created_at", "updated_at", "findings", "required_reviewer_role"],
  finding: ["finding_id", "category", "severity", "original_text", "span", "check_type", "explanation", "verification_status", "suggested_correction", "requires_human_review", "evidence"],
  evidence: ["id", "source_id", "source_version_id", "quote", "relation"],
  error: ["code", "message", "request_id"],
};
const diffs = [];
const compare = (name, obj) => {
  if (!obj || typeof obj !== "object") return diffs.push(`${name}: not an object`);
  const got = Object.keys(obj);
  const missing = EXPECT[name].filter((k) => !got.includes(k));
  const extra = got.filter((k) => !EXPECT[name].includes(k));
  if (missing.length || extra.length) diffs.push(`${name}: missing [${missing}] extra [${extra}]`);
};
const call = async (method, path, { token, body, headers = {}, origin } = {}) => {
  const res = await fetch(API + path, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(origin ? { Origin: origin } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty */ }
  return { status: res.status, data, headers: res.headers };
};
const log = (label, r, extra = "") => console.log(`${String(r.status).padEnd(4)} ${label}${extra ? "  " + extra : ""}`);

// CORS: preflight from the frontend origin
const pre = await fetch(API + "/api/reviews", { method: "OPTIONS", headers: { Origin: "http://localhost:3000", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type,idempotency-key" } });
console.log(`${pre.status}  CORS preflight from :3000 -> allow-origin=${pre.headers.get("access-control-allow-origin")} allow-headers=${pre.headers.get("access-control-allow-headers")} expose=${pre.headers.get("access-control-expose-headers")}`);
const pre3100 = await fetch(API + "/api/auth/me", { method: "OPTIONS", headers: { Origin: "http://localhost:3100", "Access-Control-Request-Method": "GET" } });
console.log(`${pre3100.status}  CORS preflight from :3100 -> allow-origin=${pre3100.headers.get("access-control-allow-origin")}`);

// Auth
let r = await call("POST", "/api/auth/login", { body: { email, password: "wrong-password" } });
log("login wrong password", r, JSON.stringify(r.data)); compare("error", r.data?.error);
r = await call("POST", "/api/auth/login", { body: { email, password } });
log("login", r, `role=${r.data?.role} token_type=${r.data?.token_type}`);
compare("login", r.data); compare("user", r.data?.user); compare("organisation", r.data?.organisation);
const token = r.data.access_token;
r = await call("GET", "/api/auth/me", { token }); log("me", r); compare("me", r.data);
r = await call("GET", "/api/auth/me"); log("me without token", r, JSON.stringify(r.data));
r = await call("GET", "/api/auth/me", { token: "garbage" }); log("me bad token", r, r.data?.error?.code);

// Sources
r = await call("GET", `/api/brands/${brand}/sources`, { token });
log("brand sources", r, `${r.data?.length} sources: ${r.data?.map((s) => `${s.title} (${s.status}, ${s.sensitivity}, type=${s.source_type}, v${s.latest_version})`).join("; ")}`);
r.data?.forEach((s) => compare("source", s));
r = await call("GET", `/api/brands/00000000-0000-4000-8000-000000000000/sources`, { token }); log("unknown brand", r, JSON.stringify(r.data));
r = await call("GET", `/api/brands/not-a-uuid/sources`, { token }); log("malformed brand id", r, JSON.stringify(r.data));

// Reviews
const text = "\u{1F3A7} The Lumen Bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled steel.";
r = await call("POST", "/api/reviews", { token, body: { brand_id: brand, text } });
log("create review (emoji text)", r, `status=${r.data?.status} findings=${r.data?.findings?.length} cache=${r.data?.served_from_cache} routing=${r.data?.required_reviewer_role} engine=${JSON.stringify(r.data?.engine)}`);
compare("review", r.data); r.data?.findings?.forEach((f) => { compare("finding", f); f.evidence.forEach((e) => compare("evidence", e)); });
const f0 = r.data?.findings?.[0];
if (f0) {
  console.log(`     finding[0]: category=${f0.category} status=${f0.verification_status} severity=${f0.severity} check=${f0.check_type} span=${JSON.stringify(f0.span)} text_cp_len=${Array.from(text).length} text_utf16_len=${text.length}`);
  console.log(`     explanation: ${f0.explanation?.slice(0, 140)}…`);
  console.log(`     original_text === submitted text: ${f0.original_text === text}`);
}
const reviewId = r.data?.id;
r = await call("GET", `/api/reviews/${reviewId}`, { token }); log("get review", r, `same status=${r.data?.status} findings=${r.data?.findings?.length}`); compare("review", r.data);
r = await call("GET", `/api/reviews/00000000-0000-4000-8000-000000000000`, { token }); log("unknown review", r, JSON.stringify(r.data));
r = await call("POST", "/api/reviews", { token, body: { brand_id: brand, text: "" } }); log("empty text", r, JSON.stringify(r.data));
r = await call("POST", "/api/reviews", { token, body: { brand_id: "00000000-0000-4000-8000-000000000000", text: "hi" } }); log("unknown brand review", r, JSON.stringify(r.data));
const key = crypto.randomUUID();
const a = await call("POST", "/api/reviews", { token, body: { brand_id: brand, text: "Idempotency test." }, headers: { "Idempotency-Key": key } });
const b2 = await call("POST", "/api/reviews", { token, body: { brand_id: brand, text: "Idempotency test." }, headers: { "Idempotency-Key": key } });
log("idempotent replay", b2, `same id=${a.data?.id === b2.data?.id}`);
const c = await call("POST", "/api/reviews", { token, body: { brand_id: brand, text: "Different body." }, headers: { "Idempotency-Key": key } });
log("key reused, other body", c, JSON.stringify(c.data));
console.log(`     X-Request-ID header present: ${!!a.headers.get("x-request-id")}`);

console.log("\nREVIEW_ID=" + reviewId);
console.log(diffs.length ? "FIELD DIFFERENCES:\n  " + diffs.join("\n  ") : "FIELDS: every response matches lib/api/types.ts");
