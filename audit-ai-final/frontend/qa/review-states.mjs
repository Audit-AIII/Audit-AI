// Review page: forces every state by changing the real GET /api/reviews/{id} response in the browser
// (nothing is stored), then checks what the page says, keyboard use and allowed_actions. Re-runs are
// answered here too, so no AI provider is called. Screenshots go to qa/out/review-states/.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/review-states.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/review-states";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const auth = { Authorization: `Bearer ${login.access_token}` };
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: auth })).json();
const base = reviews.find((r) => r.status === "needs_human_review" && r.findings.length >= 2);
const id = base.id;
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };

// Every seeded span must hold its own words, or the page would show "Span could not be located".
for (const r of reviews) {
  const cps = [...(r.text ?? "")];
  for (const f of r.findings) {
    if (r.text == null || f.scope === "document") continue;
    const held = cps.slice(f.span.start, f.span.end).join("");
    assert.equal(held.replace(/\s+/g, " ").trim(), f.original_text.replace(/\s+/g, " ").trim(), `${r.title}: span`);
  }
}
console.log("ok  seeded spans all hold their words");

const b = await chromium.launch();
const open = async (respond, { width = 1182, height = 937 } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.route(`${API}/api/reviews/${id}`, (route) => (route.request().method() === "OPTIONS" ? route.continue() : respond(route)));
  await p.goto(`${WEB}/app/review?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(500);
  return { p, ctx, errors };
};
const withReview = (over) => (route) => route.fulfill({ status: 200, contentType: "application/json", headers: CORS, body: JSON.stringify({ ...base, ...over }) });
const withError = (status, code, message) => (route) =>
  route.fulfill({ status, contentType: "application/json", headers: CORS, body: JSON.stringify({ error: { code, message, request_id: "qa-request-id" } }) });

const STATES = [
  { name: "queued", respond: withReview({ status: "queued", findings: [] }), says: /Checking your draft/ },
  { name: "analysing", respond: withReview({ status: "analysing", findings: [] }), says: /Checking your draft/ },
  { name: "failed", respond: withReview({ status: "failed", findings: [], error_summary: "the AI provider did not answer" }), says: /We couldn’t check this draft[\s\S]*did not answer[\s\S]*Try again/i },
  { name: "failed-no-rerun", respond: withReview({ status: "failed", findings: [], error_summary: "the AI provider did not answer", allowed_actions: [] }), says: /We couldn’t check this draft/i, not: /Try again/ },
  { name: "partial-rules", respond: withReview({ rules_status: "incomplete" }), says: /This check didn’t finish[\s\S]*Some brand rule checks didn’t finish[\s\S]*Check again/i },
  { name: "partial-report", respond: withReview({ report_status: "PARTIAL", error_summary: "1 claim could not be checked" }), says: /This check didn’t finish[\s\S]*Some claims couldn’t be checked/i },
  { name: "rules-not-applied", respond: withReview({ rules_status: "not_applied", rule_checks: null }), says: /Your brand rules didn’t run/ },
  { name: "empty", respond: withReview({ status: "completed", findings: [], summary_counts: { supported: 0, contradicted: 0, unverified: 0, conflicting: 0, tone: 0, needs_human_review: 0 } }), says: /No problems were flagged[\s\S]*Brand rules passed: /i },
  { name: "network", respond: (route) => route.abort(), says: /Can’t reach the server[\s\S]*Try again/i },
  { name: "403", respond: withError(403, "FORBIDDEN", "no access"), says: /You don’t have access/i, not: /Try again/ },
  { name: "404", respond: withError(404, "NOT_FOUND", "review not found"), says: /Not found[\s\S]*another workspace/i, not: /Try again/ },
  { name: "429", respond: withError(429, "RATE_LIMITED", "slow down"), says: /Too many requests[\s\S]*Try again/i },
  { name: "500", respond: withError(500, "INTERNAL_ERROR", "boom"), says: /Something went wrong[\s\S]*Try again/i },
];
for (const s of STATES) {
  const { p, ctx, errors } = await open(s.respond);
  const text = await p.locator("main").innerText();
  assert.match(text, s.says, `${s.name}: ${text.slice(0, 300)}`);
  if (s.not) assert.doesNotMatch(text, s.not, s.name);
  assert.deepEqual(errors, [], s.name);
  await p.screenshot({ path: `${OUT}/${s.name}.png`, fullPage: true });
  console.log(`ok  ${s.name}`);
  await ctx.close();
}

// Network failure: Try again recovers once the server answers.
{
  let fail = true;
  const { p, ctx } = await open((route) => (fail ? route.abort() : route.continue()));
  fail = false;
  await p.getByRole("button", { name: "Try again" }).click();
  await p.getByRole("region", { name: "What the checker found" }).waitFor();
  console.log("ok  network failure recovers with Try again");
  await ctx.close();
}

// Checking: the page looks again by itself and shows the result.
{
  let polls = 0;
  const { p, ctx } = await open((route) => {
    polls++;
    return (polls < 2 ? withReview({ status: "analysing", findings: [] }) : withReview({}))(route);
  });
  await p.getByRole("region", { name: "What the checker found" }).waitFor({ timeout: 8000 });
  console.log("ok  a running check shows its result without a reload");
  await ctx.close();
}

// Re-run from the failed screen: the POST happens and the new review opens.
{
  const { p, ctx } = await open(withReview({ status: "failed", findings: [], error_summary: "x" }));
  let called = 0;
  await p.route(`${API}/api/reviews/${id}/rerun`, (route) => {
    called++;
    return route.fulfill({ status: 503, contentType: "application/json", headers: CORS, body: JSON.stringify({ error: { code: "INTERNAL_ERROR", message: "busy", request_id: "qa" } }) });
  });
  await p.getByRole("button", { name: "Try again" }).click();
  await p.getByRole("alert").filter({ hasText: "Reference qa" }).waitFor();
  assert.equal(called, 1);
  console.log("ok  failed re-run keeps the page and shows the reference");
  await ctx.close();
}

// Summary: server counts win, missing counts are "–", never 0.
{
  const { p, ctx } = await open(withReview({ summary_counts: { supported: 7, contradicted: 5, unverified: 4, conflicting: 3, tone: 2, needs_human_review: 6 } }));
  const strip = p.getByRole("region", { name: "What the checker found" });
  const text = await strip.innerText();
  for (const expected of [/6\s+need a person/, /2 style rules/, /5\s+≠ Doesn’t match/, /3\s+⇄ Documents disagree/, /4\s+\? Not proven yet/, /7\s+✓ Matches/]) assert.match(text, expected);
  await ctx.close();
  const missing = await open(withReview({ summary_counts: undefined }));
  const text2 = await missing.p.getByRole("region", { name: "What the checker found" }).innerText();
  assert.match(text2, /–\s+need a person/);
  assert.match(text2, /–\s+≠ Doesn’t match/);
  assert.doesNotMatch(text2, /style rule/);
  await missing.ctx.close();
  console.log("ok  summary uses server counts, missing shows –");
}

// allowed_actions: controls follow the list; missing keeps today's page.
{
  const none = await open(withReview({ allowed_actions: [] }));
  assert.equal(await none.p.getByRole("button", { name: "Dismiss this finding" }).count(), 0);
  assert.equal(await none.p.getByRole("button", { name: "Add comment" }).count(), 0);
  assert.equal(await none.p.getByRole("link", { name: /Fix the wording/ }).count(), 0);
  await none.ctx.close();
  const old = await open(withReview({ allowed_actions: undefined }));
  assert.equal(await old.p.getByRole("button", { name: "Dismiss this finding" }).count(), 1);
  assert.equal(await old.p.getByRole("button", { name: "Add comment" }).count(), 1);
  await old.ctx.close();
  console.log("ok  controls follow allowed_actions");
}

// Finding details: unverified shows no quote, a contradicted one shows its proof, a bad span says so.
{
  const unverified = base.findings.find((f) => f.verification_status === "unverified");
  const quote = { id: "e1", source_id: "s", source_version_id: "v", quote: "A quote that must not appear", relation: "context", source_title: "Spec", source_version_number: 3 };
  const tampered = base.findings.map((f) => (f.finding_id === unverified.finding_id ? { ...f, evidence: [quote] } : f));
  const a = await open(withReview({ findings: tampered }));
  await a.p.locator(`[data-finding="${unverified.finding_id}"]`).click();
  const textA = await a.p.locator(".add-detail").innerText();
  assert.doesNotMatch(textA, /A quote that must not appear/);
  assert.match(textA, /Not proven yet/);
  assert.doesNotMatch(textA, /No approved document covers this/, "not repeated under the note");
  await a.ctx.close();

  const contradicted = { ...unverified, verification_status: "contradicted", evidence: [{ ...quote, relation: "contradicts" }], suggested_correction: "The evidence-backed wording", safer_wording: null, validation_status: "validated", review_reasons: ["contradicted", "compound_under_cited"] };
  const b1 = await open(withReview({ findings: base.findings.map((f) => (f.finding_id === unverified.finding_id ? contradicted : f)) }));
  await b1.p.locator(`[data-finding="${unverified.finding_id}"]`).click();
  const textB = await b1.p.locator(".add-detail").innerText();
  for (const expected of [/Spec · version 3/i, /Disagrees/i, /A quote that must not appear/, /backed by your documents/i, /Quote verified/i, /Medium|High|Low|Critical/, /Only part of this claim has evidence/]) assert.match(textB, expected);
  await b1.p.screenshot({ path: `${OUT}/finding-full.png`, fullPage: true });
  await b1.ctx.close();

  const c = await open(withReview({ findings: base.findings.map((f) => (f.finding_id === unverified.finding_id ? { ...f, span: { start: 0, end: 3 } } : f)) }));
  await c.p.locator(`[data-finding="${unverified.finding_id}"]`).click();
  assert.match(await c.p.locator(".add-detail").innerText(), /Span could not be located/i);
  await c.ctx.close();
  console.log("ok  finding details");
}

// Keyboard: arrows move, Enter opens the details, Esc comes back. Picks link both ways.
{
  const { p, ctx, errors } = await open(withReview({}));
  const rows = p.locator(".problem");
  const [first, second] = [await rows.nth(0).getAttribute("data-finding"), await rows.nth(1).getAttribute("data-finding")];
  await rows.nth(0).focus();
  await p.keyboard.press("ArrowDown");
  await p.waitForFunction((id) => document.activeElement?.getAttribute("data-finding") === id, second);
  assert.equal(await rows.nth(1).getAttribute("aria-pressed"), "true");
  await p.keyboard.press("ArrowUp");
  await p.waitForFunction((id) => document.activeElement?.getAttribute("data-finding") === id, first);
  await p.keyboard.press("Enter");
  assert.equal(await p.evaluate(() => document.activeElement?.classList.contains("add-detail")), true, "Enter opens details");
  await p.keyboard.press("Escape");
  assert.equal(await p.evaluate(() => document.activeElement?.getAttribute("data-finding")), first, "Esc returns to the row");
  await p.locator(".heat__mark").last().click();
  assert.equal(await rows.nth(0).getAttribute("aria-pressed"), "false", "clicking the draft moves the list");
  assert.deepEqual(errors, []);
  console.log("ok  keyboard and draft/list linking");
  await ctx.close();
}

// The real page at both sizes, with no intercepted data.
for (const [name, width, height] of [["real-desktop", 1182, 937], ["real-mobile", 390, 844]]) {
  const { p, ctx, errors } = await open((route) => route.continue(), { width, height });
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, `${name}: horizontal scroll`);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  await ctx.close();
}
console.log("ok  real page, no horizontal scroll");
await b.close();
console.log("review states: all passed");
