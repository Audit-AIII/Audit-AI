// End-to-end check of the API wiring against a fake backend that returns the documented shapes
// (services/api/API.md + schemas.py). Run with the dev server on :3000: node qa/api-e2e.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const API = "http://localhost:8000";
const BRAND = "11111111-2222-4333-8444-555555555555";
const ORG = { id: "b2a1f3c4-5d6e-4f70-8a9b-0c1d2e3f4a5b", name: "Seed Demo Org", slug: "seed" };
const USER = { id: "6f1e9a2e-2d2b-4e34-9a5a-2e4f2d2c9c11", email: "admin@seed.inkloom.demo", display_name: null };
const err = (code, message) => ({ error: { code, message, request_id: "req-test-123" } });
const now = "2026-10-23T10:00:00Z";
const review = (id, status, findings, extra = {}) => ({
  id,
  content_version_id: "c0ffee00-0000-4000-8000-000000000001",
  status,
  report_status: null,
  engine: { provider: "openrouter", model_id: "google/gemini-2.5-flash", prompt_version: "extract-claims-v1", contract_version: "0.1.0" },
  error_summary: null,
  served_from_cache: false,
  started_at: now,
  completed_at: now,
  created_at: now,
  updated_at: now,
  findings,
  required_reviewer_role: null,
  ...extra,
});

// Emoji before the claims: code point offsets differ from UTF-16 ones.
const TEXT = "\u{1F3A7}\u{1F3A7} The Aero lasts 24 hours on one charge. Lumen was founded in 2015.";
const cp = (s) => Array.from(s).length;
const at = (needle) => {
  const start = cp(TEXT.slice(0, TEXT.indexOf(needle)));
  return { start, end: start + cp(needle) };
};
const REAL = review("rev-real", "needs_human_review", [
  {
    finding_id: "f1", category: "product_claim", severity: "high",
    original_text: "The Aero lasts 24 hours on one charge.", span: at("The Aero lasts 24 hours on one charge."), check_type: "retrieval",
    explanation: "The spec gives 12 hours.", verification_status: "contradicted",
    suggested_correction: "The Aero lasts 12 hours on one charge.", requires_human_review: true,
    evidence: [{ id: "e1", source_id: "s1", source_version_id: "sv1", quote: "Battery life: 12 hours", relation: "contradicts" }],
  },
  {
    finding_id: "f2", category: "company_fact", severity: "medium",
    original_text: "Lumen was founded in 2015.", span: at("Lumen was founded in 2015."), check_type: "retrieval",
    explanation: "No approved source covers the founding year.", verification_status: "unverified",
    suggested_correction: null, requires_human_review: true, evidence: [],
  },
]);
const STUB_TEXT = "Meet the new Aero earbuds \u{1F3A7}. One charge lasts 24 hours.";
const STUB = review(
  "rev-stub",
  "needs_human_review",
  [
    {
      finding_id: "fs", category: "stub", severity: "medium", original_text: STUB_TEXT,
      span: { start: 0, end: cp(STUB_TEXT) }, check_type: "semantic",
      explanation: "[STUB OUTPUT] No LLM provider is configured for this backend. This finding is fixed placeholder content.",
      verification_status: "unverified", suggested_correction: null, requires_human_review: true, evidence: [],
    },
  ],
  { engine: { provider: "stub-unconfigured", model_id: null, prompt_version: null, contract_version: "0.1.0" } },
);

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const pageErrors = [];
p.on("pageerror", (e) => pageErrors.push(e.message));
const seen = [];
let nextPost = { status: 201, body: STUB };
let getOverride = null;

await p.route(`${API}/**`, async (route) => {
  const req = route.request();
  const path = new URL(req.url()).pathname;
  const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
  seen.push(`${req.method()} ${path} auth=${!!req.headers().authorization} idem=${!!req.headers()["idempotency-key"]}`);
  const json = (status, body) =>
    route.fulfill({ status, contentType: "application/json", headers: { ...cors, "X-Request-ID": "req-test-123" }, body: JSON.stringify(body) });
  if (path === "/api/auth/login") {
    const { password } = JSON.parse(req.postData());
    return password === "right"
      ? json(200, { access_token: "tok", token_type: "bearer", user: USER, organisation: ORG, role: "admin" })
      : json(401, err("UNAUTHENTICATED", "invalid email or password"));
  }
  if (path === "/api/auth/me") return json(200, { user: USER, organisation: ORG, role: "admin" });
  if (path === "/api/brands") return json(200, [{ id: BRAND, name: "Lumen Goods", description: null, approved_source_count: 2, created_at: now }]);
  if (path === `/api/brands/${BRAND}/sources`)
    return json(200, [
      { id: "s1", brand_profile_id: BRAND, title: "Product spec", status: "approved", sensitivity: "normal", source_type: null, latest_version: 1, created_at: now, updated_at: now },
      { id: "s2", brand_profile_id: BRAND, title: "Brand guide", status: "approved", sensitivity: "confidential", source_type: "pdf", latest_version: 4, created_at: now, updated_at: now },
    ]);
  if (path.startsWith("/api/brands/")) return json(404, err("NOT_FOUND", "brand not found"));
  if (path === "/api/reviews" && req.method() === "POST") return json(nextPost.status, nextPost.body);
  if (path.startsWith("/api/reviews/")) {
    if (getOverride) return json(getOverride.status, getOverride.body);
    const id = path.split("/").pop();
    if (id === "rev-stub") return json(200, STUB);
    if (id === "rev-real") return json(200, REAL);
    return json(404, err("NOT_FOUND", "review not found"));
  }
  return json(404, err("NOT_FOUND", "not found"));
});

const go = (u) => p.goto(`http://localhost:3000${u}`, { waitUntil: "networkidle" });
const text = (sel) => p.locator(sel).first().innerText();

// 1. Login: wrong password shows the plain error, right password signs in, /me fills the status bar
await go("/login");
await p.fill("#a-email", USER.email);
await p.fill("#a-password", "wrong");
await p.click("button[type=submit]");
await p.waitForSelector(".auth__alert--bad");
assert.match(await text(".auth__alert--bad"), /match an account/);
await p.fill("#a-password", "right");
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 8000 });
await p.waitForTimeout(2500);
assert.match(await text(".app__status-sample"), /Seed Demo Org/i);
console.log("ok  login: 401 message, success, /me");

// 2. Sources: brand picked automatically from GET /api/brands, documents listed
await p.waitForSelector(".rows__item");
assert.equal(await p.locator("text=Brand ID").count(), 0);
assert.equal(await p.locator(".rows__item").count(), 2);
assert.match(await text(".rows"), /Brand guide[\s\S]*PDF · Version 4/);
console.log("ok  sources: brand from /api/brands, list");

// 3. Draft -> POST (stub) -> Review; refresh keeps it
await go("/app/draft");
await p.fill(".draft__text", STUB_TEXT);
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=rev-stub");
await p.waitForSelector(".app-alert--placeholder");
assert.match(await text(".stage-head__status"), /Placeholder result/i);
assert.equal(await p.locator(".chip--contradicted, .chip--unverified, .chip--supported").count(), 0, "stub shows no verdict chip");
assert.equal(await p.locator(".heat__placeholder").count(), 1);
await p.screenshot({ path: "qa/out/api-stub.png" });
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".app-alert--placeholder");
assert.equal(await p.locator(".problem").count(), 1);
console.log("ok  draft -> POST /api/reviews -> stub placeholder, survives refresh");

// 4. Real findings on emoji text: highlights land on the right words (code points converted)
await p.evaluate((t) => localStorage.setItem("audit-ai.review-text.rev-real", t), TEXT);
await go("/app/review?id=rev-real");
await p.waitForSelector(".heat__bad");
assert.equal(await text(".heat__bad"), "The Aero lasts 24 hours on one charge.");
assert.equal(await text(".heat__warn"), "Lumen was founded in 2015.");
assert.match(await text(".stage-head__status"), /2 things to look at/i);
await p.screenshot({ path: "qa/out/api-real.png" });
await p.click(".problem >> nth=1");
assert.match(await text(".finding-detail"), /proven yet, not that it/);
// Refresh without the local copy: findings still show, with a note instead of highlights
await p.evaluate(() => localStorage.removeItem("audit-ai.review-text.rev-real"));
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".problem");
assert.equal(await p.locator(".problem").count(), 2);
assert.equal(await p.locator(".heat__mark").count(), 0);
console.log("ok  real review: code-point spans highlight correctly; refresh keeps findings");

// 5. Errors
await go("/app/review?id=nope");
await p.waitForSelector(".app-alert--bad");
assert.match(await text(".app-alert--bad"), /find this review/);
assert.match(await text(".app-empty"), /req-test-123/);
getOverride = { status: 500, body: err("INTERNAL_ERROR", "an internal error occurred") };
await go("/app/review?id=rev-real");
await p.waitForSelector(".app-alert--bad");
assert.match(await text(".app-alert--bad"), /went wrong on the server/);
getOverride = { status: 403, body: err("FORBIDDEN", "forbidden") };
await go("/app/review?id=rev-real");
await p.waitForSelector(".app-alert--bad");
assert.match(await text(".app-alert--bad"), /allow this/);
await go("/app/draft");
await p.fill(".draft__text", "x");
nextPost = { status: 422, body: err("VALIDATION_ERROR", "invalid request: body.text") };
await p.click("button[type=submit]");
await p.waitForSelector(".app-alert--bad");
assert.match(await text(".app-alert--bad"), /body\.text/);
nextPost = { status: 429, body: err("RATE_LIMITED", "too many submissions") };
await p.click("button[type=submit]");
await p.waitForFunction(() => /wait a minute/.test(document.querySelector(".app-alert--bad")?.textContent ?? ""));
getOverride = { status: 401, body: err("UNAUTHENTICATED", "token expired") };
await go("/app/review?id=rev-real");
await p.waitForURL("**/login?expired=1", { timeout: 8000 });
await p.waitForSelector(".auth__alert");
assert.match(await text(".auth__alert"), /session ended/);
assert.equal(await p.evaluate(() => localStorage.getItem("audit-ai.session")), null);
console.log("ok  errors: 404 / 500 / 403 / 422 / 429 shown; 401 signs out -> /login?expired=1");

assert.ok(seen.some((s) => s.startsWith("POST /api/reviews auth=true idem=true")), "POST sends token + Idempotency-Key");
assert.deepEqual(pageErrors, []);
console.log("ok  no page errors; endpoints hit:", [...new Set(seen.map((s) => s.split(" auth")[0]))].join(", "));
await b.close();
