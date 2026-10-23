// Self-serve onboarding against a fake backend that implements the agreed contract for the routes
// Member 3 has not merged yet (register, GET/POST /api/brands, /api/reviews/upload, ReviewOut.text).
// It also checks the exact multipart field names the frontend sends. Frontend on :3000.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";

const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const fx = (f) => path.resolve("qa/fixtures", f);
const now = "2026-10-23T12:00:00Z";
const err = (code, message) => ({ error: { code, message, request_id: "req-contract-1" } });
const cp = (s) => Array.from(s).length;

// --- fake backend state ---
const users = new Map(); // lower-cased email -> user
let brand = null;
const sources = [];
const reviews = new Map();
let signupsLeft = 5;
const multipartSeen = {};

const review = (id, text, title) => ({
  id, content_version_id: `cv-${id}`, status: "needs_human_review", report_status: null,
  engine: { provider: "stub-unconfigured", model_id: null, prompt_version: null, contract_version: "0.1.0" },
  error_summary: null, served_from_cache: false, started_at: now, completed_at: now, created_at: now, updated_at: now,
  required_reviewer_role: "brand_manager",
  content_item_id: `ci-${id}`, brand_id: brand.id, title: title ?? null, version_number: 1, text,
  findings: [{
    finding_id: `f-${id}`, category: "stub", severity: "medium", original_text: text, span: { start: 0, end: cp(text) },
    check_type: "semantic", explanation: "[STUB OUTPUT] No LLM provider is configured.", verification_status: "unverified",
    suggested_correction: null, requires_human_review: true, evidence: [],
  }],
});
const parts = (buf, ct) => {
  const boundary = /boundary=(.+)$/.exec(ct)?.[1];
  const out = {};
  if (!boundary) return out;
  for (const chunk of buf.toString("latin1").split(`--${boundary}`)) {
    const m = /name="([^"]+)"(?:; filename="([^"]*)")?\r\n(?:Content-Type: [^\r]+\r\n)?\r\n([\s\S]*)\r\n$/.exec(chunk);
    if (m) out[m[1]] = m[2] !== undefined ? { filename: m[2], size: m[3].length } : m[3];
  }
  return out;
};

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1182, height: 937 } });
const p = await ctx.newPage();
const consoleErrors = [];
p.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
p.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
const log = [];

await ctx.route(`${API}/**`, async (route) => {
  const req = route.request();
  const cors = { "Access-Control-Allow-Origin": WEB, "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*" };
  if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: cors });
  const { pathname: p2 } = new URL(req.url());
  const ct = req.headers()["content-type"] ?? "";
  const json = (status, body) => {
    log.push(`${req.method()} ${p2} ${status}${ct.startsWith("multipart") ? " [multipart+boundary]" : ""}`);
    return route.fulfill({ status, contentType: "application/json", headers: cors, body: JSON.stringify(body) });
  };
  const form = ct.startsWith("multipart") ? parts(req.postDataBuffer(), ct) : null;
  if (form) multipartSeen[p2.replace(/[0-9a-f-]{36}|b-1|s-\d+/g, "{id}")] = Object.keys(form).sort();
  const body = ct.includes("json") ? JSON.parse(req.postData() || "{}") : null;

  if (p2 === "/api/auth/register") {
    if (signupsLeft-- <= 0) return json(429, err("RATE_LIMITED", "too many sign-ups"));
    const key = body.email.toLowerCase();
    if (users.has(key)) return json(409, err("CONFLICT", "an account with this email already exists"));
    if (!body.password || body.password.length < 8) return json(422, err("VALIDATION_ERROR", "invalid request: body.password"));
    const user = { id: "u-1", email: body.email, display_name: body.display_name ?? null };
    users.set(key, user);
    brand = { id: "b-1", name: body.brand_name ?? "My brand", description: null, approved_source_count: 0, created_at: now };
    return json(201, { access_token: "tok-1", token_type: "bearer", expires_in: 43200, user, organisation: { id: "o-1", name: "Nova Org", slug: "nova" }, role: "admin", brand });
  }
  if (p2 === "/api/auth/me") return json(200, { user: users.get("nova@example.com"), organisation: { id: "o-1", name: "Nova Org", slug: "nova" }, role: "admin" });
  if (p2 === "/api/brands" && req.method() === "GET") return json(200, [{ ...brand, approved_source_count: sources.filter((s) => s.status === "approved").length }]);
  if (p2 === `/api/brands/${brand?.id}/sources` && req.method() === "GET") return json(200, sources);
  if (p2 === `/api/brands/${brand?.id}/sources` && req.method() === "POST") {
    if (!/\.(pdf|docx|txt)$/i.test(form.file.filename) || form.file.filename === "image-only.pdf")
      return json(422, err("VALIDATION_ERROR", "could not extract any text from this file"));
    const s = { id: `s-${sources.length + 1}`, brand_profile_id: brand.id, title: form.title, status: form.approve === "true" ? "approved" : "draft",
      sensitivity: form.sensitivity, source_type: form.file.filename.split(".").pop(), latest_version: 1, created_at: now, updated_at: now };
    sources.push(s);
    return json(201, s);
  }
  if (p2 === "/api/reviews" && req.method() === "POST") {
    const r = review(`r-${reviews.size + 1}`, body.text, body.title);
    reviews.set(r.id, r);
    return json(201, r);
  }
  if (p2 === "/api/reviews/upload") {
    if (form.file.filename !== "launch-post.docx") return json(422, err("VALIDATION_ERROR", "unsupported or unreadable file"));
    const r = review(`r-${reviews.size + 1}`, "New Lumen Bottle launch post.\nThe Lumen Bottle keeps drinks cold for 24 hours and is made from 90% recycled steel.", form.title);
    reviews.set(r.id, r);
    return json(201, r);
  }
  if (p2.startsWith("/api/reviews/")) {
    const r = reviews.get(p2.split("/").pop());
    return r ? json(200, r) : json(404, err("NOT_FOUND", "review not found"));
  }
  return json(404, err("NOT_FOUND", `not found: ${p2}`));
});

const text = (sel) => p.locator(sel).first().innerText();
const step = (s) => console.log(`\n# ${s}`);
const flush = () => {
  log.splice(0).forEach((l) => console.log(`   ${l}`));
};

step("1) sign up -> lands on / signed in");
await p.goto(`${WEB}/login?mode=signup`, { waitUntil: "networkidle" });
await p.fill("#a-name", "Nova Writer");
await p.fill("#a-email", "nova@example.com");
await p.fill("#a-password", "short");
await p.fill("#a-confirm", "short");
await p.click("button[type=submit]");
assert.equal(log.length, 0, "browser blocks a 5-character password before any request");
await p.fill("#a-password", "correct horse 1");
await p.fill("#a-confirm", "correct horse 2");
await p.click("button[type=submit]");
assert.equal(log.length, 0, "mismatched confirm is blocked before any request");
assert.match(await p.$eval("#a-confirm", (e) => e.validationMessage), /don't match/);
await p.fill("#a-confirm", "correct horse 1");
await p.fill("#a-brand", "Nova Bottles");
await p.click("button[type=submit]");
await p.waitForURL(`${WEB}/`, { timeout: 15000 });
await p.waitForSelector(".account__email", { timeout: 10000 });
assert.equal(await text(".account__email"), "nova@example.com");
flush();
console.log(`   ok: on "/" with "${await text(".account__email")}" in the header`);

step("2) Workspace -> Sources");
await p.click("a.nav__cta");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.waitForSelector(".approved-count");
assert.equal(await p.locator("text=Brand ID").count(), 0);
assert.match(await text(".panel:nth-child(2) .panel__title"), /Nova Bottles/i);
assert.equal(await p.locator(".panel select").count(), 0, "no brand picker with one brand");
flush();

step("3) upload a PDF (approve=true for admins)");
await p.setInputFiles(".upload-form input[type=file]", fx("brand-facts.pdf"));
await p.check(".upload-form .option input");
await p.click(".upload-form button[type=submit]");
await p.waitForSelector(".upload-form .app-alert--ok");
await p.waitForFunction(() => document.querySelector(".approved-count")?.textContent === "1");
assert.match(await text(".rows"), /brand facts[\s\S]*Approved[\s\S]*Private/i);
flush();
console.log(`   multipart fields sent: ${JSON.stringify(multipartSeen["/api/brands/{id}/sources"])}`);
assert.deepEqual(multipartSeen["/api/brands/{id}/sources"], ["approve", "file", "sensitivity", "title"]);

step("4) Draft: brand + count, paste text, then a .docx");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForFunction(() => /1 approved document$/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
console.log(`   brand pill: "${await text(".brand-pill__id")}"`);
await p.fill(".draft__text", "Nova Bottles keep drinks cold for 24 hours.");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*");
await p.waitForSelector(".heat__mark");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForSelector(".brand-pill__id");
await p.setInputFiles(".dropzone--small input[type=file]", fx("launch-post.docx"));
assert.equal(await p.locator(".draft__text").isDisabled(), true, "textarea locked while a file is chosen");
await p.fill("input[placeholder^='e.g. Earbuds']", "Launch post");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*");
await p.waitForSelector(".heat__mark");
assert.match(await text(".heat"), /keeps drinks cold for 24 hours and is made from 90% recycled steel/);
flush();
console.log(`   multipart fields sent: ${JSON.stringify(multipartSeen["/api/reviews/upload"])}`);
assert.deepEqual(multipartSeen["/api/reviews/upload"], ["brand_id", "file", "title"]);
console.log("   ok: review shows the text extracted from the .docx (ReviewOut.text)");

step("5) refresh: text comes from the API (not this browser's copy)");
await p.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("audit-ai.review-text.")).forEach((k) => localStorage.removeItem(k)));
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".heat__mark");
assert.match(await text(".heat"), /90% recycled steel/);
flush();
console.log("   ok: text + finding shown after refresh with local copies cleared");

step("6) error paths");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForSelector(".brand-pill__id");
await p.setInputFiles(".dropzone--small input[type=file]", fx("setup.exe"));
console.log(`   .exe on Draft (client-side): "${await text(".app-alert--bad")}"`);
assert.match(await text(".app-alert--bad"), /Only PDF, Word/);
await p.setInputFiles(".dropzone--small input[type=file]", fx("image-only.pdf"));
await p.click("button[type=submit]");
await p.waitForFunction(() => /couldn’t read that file/.test(document.querySelector(".app-alert--bad")?.textContent ?? ""));
console.log(`   image-only PDF on Draft: "${await text(".app-alert--bad")}"`);
// sign out, then sign up again with the same email in UPPERCASE
await p.click(".account__who");
await p.click(".account__menu button");
await p.waitForURL(`${WEB}/`, { timeout: 15000 });
await p.goto(`${WEB}/login?mode=signup`, { waitUntil: "networkidle" });
await p.fill("#a-email", "NOVA@EXAMPLE.COM");
await p.fill("#a-password", "another pass 9");
await p.fill("#a-confirm", "another pass 9");
await p.click("button[type=submit]");
await p.waitForSelector(".auth__alert--bad");
assert.match(await text(".auth__alert--bad"), /already exists\. Sign in instead/);
console.log(`   same email, UPPERCASE: "${await text(".auth__alert--bad")}"`);
signupsLeft = 0;
await p.fill("#a-email", "other@example.com");
await p.click("button[type=submit]");
await p.waitForFunction(() => /Too many sign-ups/.test(document.querySelector(".auth__alert--bad")?.textContent ?? ""));
console.log(`   429: "${await text(".auth__alert--bad")}"`);
flush();

console.log(`\nconsole errors: ${consoleErrors.length ? consoleErrors.join("\n  ") : "none"}`);
assert.deepEqual(consoleErrors.filter((e) => !/status of 4\d\d/.test(e)), []);
await b.close();
