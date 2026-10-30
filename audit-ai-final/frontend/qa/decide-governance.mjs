// Decide and Queue with governance fields: real review, with the example payloads from
// contract/examples layered on in the browser (nothing is stored), so each role can be seen without
// a team in the seed. Workflow POSTs are answered here. Phase 10 walks the same flow for real.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/decide-governance.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/decide-governance";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const example = (n) => JSON.parse(readFileSync(`qa/fixtures/governance/governance_${n}.json`, "utf8"));
const { id: _i, content_version_id: _c, content_item_id: _it, status: _s, title: _t, version_number: _v, ...teamApprover } = example("review_item_team_approver");
const { id: _i2, content_version_id: _c2, content_item_id: _it2, status: _s2, title: _t2, version_number: _v2, ...teamWriter } = example("review_item_team_writer");

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const auth = { Authorization: `Bearer ${login.access_token}` };
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: auth })).json();
const base = reviews.find((r) => r.status === "needs_human_review");
const id = base.id;
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });

const b = await chromium.launch();
const open = async (over, { width = 1182, height = 937, before } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  const state = { over, gets: 0 };
  await p.route(`${API}/api/reviews/${id}`, (route) => {
    if (route.request().method() === "OPTIONS") return route.continue();
    state.gets++;
    return route.fulfill(json(200, { ...base, ...state.over }));
  });
  await before?.(p);
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  return { p, ctx, errors, state };
};
const buttons = async (p) => (await p.locator(".decisions").getByRole("button").allInnerTexts()).map((s) => s.trim());

// Real personal workspace: today's controls, no team clutter, no untrue "reviewer" wording.
{
  const ctx = await b.newContext({ viewport: { width: 1182, height: 937 } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".add-gov");
  assert.deepEqual(await buttons(p), ["Approve", "Send back for changes", "Reject"]);
  const bar = await p.locator(".add-gov").innerText();
  assert.match(bar, /Solo sign-off/);
  assert.match(bar, /no evidence either way\./);
  assert.doesNotMatch(bar, /a reviewer must|Author|Owner|Assigned/);
  assert.doesNotMatch(await p.locator("main").innerText(), /Send for review/);
  await p.screenshot({ path: `${OUT}/personal-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  personal workspace");
}

// Older backend: no governance fields at all, so today's page.
{
  const { p, ctx } = await open({ workflow_status: undefined, allowed_actions: undefined, workspace: undefined, approval_mode: undefined, routing_reason: undefined, risk_level: undefined, author: undefined, owner: undefined, assigned_reviewer: undefined, is_current_version: undefined });
  assert.equal(await p.locator(".add-gov").count(), 0);
  assert.deepEqual(await buttons(p), ["Approve", "Send back for changes", "Reject"]);
  await ctx.close();
  console.log("ok  older backend keeps today's page");
}

// Team approver example.
{
  const { p, ctx, errors } = await open(teamApprover);
  assert.deepEqual(await buttons(p), ["Approve", "Send back for changes", "Reject"]);
  const bar = await p.locator(".add-gov").innerText();
  for (const expected of [/Wren Writer/, /Remy Reviewer/, /Reviewed/i, /High/, /a reviewer must check/]) assert.match(bar, expected);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/team-approver-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  team approver");
}

// Team writer example: no approve.
{
  const { p, ctx } = await open(teamWriter);
  const list = await buttons(p);
  assert.ok(!list.includes("Approve"), `writer sees ${list}`);
  await p.screenshot({ path: `${OUT}/team-writer-desktop.png`, fullPage: true });
  await ctx.close();
  console.log(`ok  team writer sees: ${list.join(", ") || "no decision buttons"}`);
}

// Nothing allowed: says so, no note box.
{
  const { p, ctx } = await open({ ...teamWriter, allowed_actions: [] });
  assert.deepEqual(await buttons(p), []);
  assert.equal(await p.locator(".decide__note").count(), 0);
  assert.match(await p.locator("main").innerText(), /nothing for you to do/i);
  await ctx.close();
  console.log("ok  nothing allowed");
}

// Unknown workflow status doesn't crash.
{
  const { p, ctx, errors } = await open({ ...teamApprover, workflow_status: "escalated" });
  assert.match(await p.locator(".add-gov").innerText(), /In progress/);
  assert.deepEqual(errors, []);
  await ctx.close();
  console.log("ok  unknown workflow status");
}

// A refused approve shows the API's message, keeps the note and doesn't move on.
{
  const { p, ctx } = await open(teamApprover);
  await p.route(`${API}/api/content-versions/${base.content_version_id}/approve`, (route) =>
    route.fulfill(json(403, { error: { code: "SELF_APPROVAL_FORBIDDEN", message: "you wrote this draft, so someone else has to approve it", request_id: "qa-approve" } })),
  );
  await p.fill(".decide__note", "keep me");
  await p.getByRole("button", { name: "Approve", exact: true }).click();
  const alert = p.getByRole("alert").filter({ hasText: "someone else has to approve" });
  await alert.waitFor();
  assert.match(await alert.innerText(), /qa-approve/);
  assert.equal(await p.inputValue(".decide__note"), "keep me");
  await ctx.close();
  console.log("ok  refused approve shows why, keeps the note");
}

// Workflow actions: right call, then the status comes from a re-fetch.
{
  const { p, ctx, state } = await open({ ...teamWriter, allowed_actions: ["submit"], workflow_status: "draft" });
  const calls = [];
  await p.route(`${API}/api/content/${base.content_item_id}/submit`, (route) => {
    calls.push(route.request().postDataJSON());
    state.over = { ...state.over, allowed_actions: [], workflow_status: "in_review" };
    return route.fulfill(json(200, { content_item_id: base.content_item_id, version_number: 1, workflow_status: "in_review", risk_level: "high", required_reviewer_role: "reviewer", routing_reason: null, assigned_reviewer: null }));
  });
  const before = state.gets;
  await p.getByRole("button", { name: "Send for review" }).click();
  await p.getByRole("status").filter({ hasText: "Sent for review" }).waitFor();
  await p.waitForFunction(() => /In review/.test(document.querySelector(".add-gov")?.textContent ?? ""));
  assert.deepEqual(calls, [{ content_version_id: base.content_version_id }]);
  assert.ok(state.gets > before, "re-fetched after the action");
  await ctx.close();
  console.log("ok  submit calls the API and re-fetches");
}

// Assign, mark reviewed and publish (with its confirm).
{
  const { p, ctx } = await open(
    { ...teamApprover, allowed_actions: ["assign", "mark_reviewed", "publish"], assigned_reviewer: null },
    { before: (page) => page.route(`${API}/api/workspace/members`, (route) => route.fulfill(json(200, example("members")))) },
  );
  const calls = {};
  const answer = { content_item_id: base.content_item_id, version_number: 1, workflow_status: "reviewed", risk_level: "high", required_reviewer_role: "reviewer", routing_reason: null, assigned_reviewer: null };
  for (const [name, url] of [["assign", `${API}/api/content/${base.content_item_id}/assign`], ["reviewed", `${API}/api/content/${base.content_item_id}/mark-reviewed`], ["publish", `${API}/api/content-versions/${base.content_version_id}/publish`]]) {
    await p.route(url, (route) => {
      calls[name] = route.request().postDataJSON();
      return route.fulfill(json(200, answer));
    });
  }
  await p.locator(".add-assign select").selectOption({ label: "Remy Reviewer" });
  await p.getByRole("button", { name: "Assign" }).click();
  await p.waitForFunction(() => /Reviewer assigned/.test(document.body.innerText));
  assert.deepEqual(calls.assign, { reviewer_user_id: "22222222-2222-4222-8222-222222222222" });
  await p.fill(".decide__note", "Checked the price.");
  await p.getByRole("button", { name: "Mark as reviewed" }).click();
  await p.waitForFunction(() => /Marked as reviewed/.test(document.body.innerText));
  assert.deepEqual(calls.reviewed, { content_version_id: base.content_version_id, note: "Checked the price." });
  await p.locator(".decisions").getByRole("button", { name: "Mark as published" }).click();
  assert.equal(calls.publish, undefined, "publish waits for the confirm");
  await p.locator("dialog").getByRole("button", { name: "Mark as published" }).click();
  await p.waitForFunction(() => /Marked as published/.test(document.body.innerText));
  await ctx.close();
  console.log("ok  assign, mark reviewed, publish");
}

// Stale version.
{
  const { p, ctx } = await open({ ...teamApprover, is_current_version: false, allowed_actions: ["request_changes"] });
  assert.match(await p.locator("main").innerText(), /newer version of this draft exists/i);
  await ctx.close();
  console.log("ok  stale version");
}

// Mobile: stacked, no sideways scroll.
{
  const { p, ctx } = await open(teamApprover, { width: 390, height: 844 });
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
  await p.screenshot({ path: `${OUT}/team-approver-mobile.png`, fullPage: true });
  await ctx.close();
  console.log("ok  mobile");
}

// Queue: API risk and workflow columns on real data, and the filter works.
{
  const ctx = await b.newContext({ viewport: { width: 1182, height: 937 } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  await p.goto(`${WEB}/app/queue`, { waitUntil: "networkidle" });
  await p.waitForSelector(".add-table");
  const head = await p.locator(".add-table").first().locator("th").allInnerTexts();
  assert.ok(head.map((h) => h.toLowerCase()).includes("workflow"), `headers: ${head}`);
  assert.ok(!head.map((h) => h.toLowerCase()).includes("reviewer"), "no reviewer column in a personal workspace");
  const before = await p.locator(".add-table tbody tr").count();
  await p.locator(".add-queue-filter select").selectOption({ label: "Approved" });
  const after = await p.locator(".add-table tbody tr").count();
  assert.ok(after < before, `filter ${before} -> ${after}`);
  await p.locator(".add-queue-filter select").selectOption({ value: "all" });
  await p.screenshot({ path: `${OUT}/queue-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  queue");
}
await b.close();
console.log("decide governance: all passed");
