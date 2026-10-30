// Team page: a real invite and revoke against the backend, then forced cases in the browser for the
// roles and refusals the seed can't produce (it has no team). Revokes what it creates.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/team-page.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/team-page";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });
const example = (n) => JSON.parse(readFileSync(`qa/fixtures/governance/governance_${n}.json`, "utf8"));

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const session = { email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role: login.role };

const b = await chromium.launch();
const open = async ({ width = 1182, height = 937, before } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: WEB });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  const logged = [];
  p.on("console", (m) => logged.push(m.text()));
  await before?.(p);
  await p.goto(`${WEB}/app/team`, { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  return { p, ctx, errors, logged };
};
const invite = (p, email, role) => p.getByLabel("Email").fill(email).then(async () => {
  if (role) await p.getByLabel("Role", { exact: true }).selectOption(role);
  await p.getByRole("button", { name: "Create invitation" }).click();
});
const mockTeam = (page, members = example("members"), invitations = example("invitations_list")) =>
  Promise.all([
    page.route(`${API}/api/workspace/members`, (r) => (r.request().method() === "GET" ? r.fulfill(json(200, members)) : r.fallback())),
    page.route(`${API}/api/workspace/invitations`, (r) => (r.request().method() === "GET" ? r.fulfill(json(200, invitations)) : r.fallback())),
  ]);

// Real: one member, invite, link shown once, not stored, revoke, gone from pending.
{
  const { p, ctx, errors, logged } = await open();
  let main = await p.locator("main").innerText();
  assert.match(main, /1 member/i);
  assert.match(main, /It’s just you here/);
  assert.match(main, /\(you\)/);
  assert.equal(await p.getByRole("button", { name: "Remove" }).count(), 0, "not offered on your own row");
  assert.equal(await p.getByLabel(/^Role for/).count(), 0, "own role not offered");
  await p.screenshot({ path: `${OUT}/one-member-desktop.png`, fullPage: true });

  const email = `qa-team-${Date.now()}@example.com`;
  await invite(p, email, "reviewer");
  const input = p.getByLabel("Invitation link");
  await input.waitFor();
  const link = await input.inputValue();
  assert.ok(link.startsWith(`${WEB}/invite/accept?token=`), link);
  const token = new URL(link).searchParams.get("token");
  await p.getByRole("button", { name: "Copy link" }).click();
  await p.getByText("✓ Copied").waitFor();
  assert.equal(await p.evaluate(() => navigator.clipboard.readText()), link);
  main = await p.locator("main").innerText();
  assert.match(main, /doesn’t send email/);
  assert.match(main, /only time the link is shown/);
  await p.getByRole("listitem").filter({ hasText: email }).waitFor();

  // The token must not be anywhere it could outlive this page.
  const stored = await p.evaluate(() => JSON.stringify({ l: { ...localStorage }, s: { ...sessionStorage }, c: document.cookie, u: location.href }));
  assert.ok(!stored.includes(token), "token not in storage, cookies or the URL");
  assert.ok(!logged.some((l) => l.includes(token)), "token not logged");
  await p.screenshot({ path: `${OUT}/invited-desktop.png`, fullPage: true });

  // Duplicate: API's refusal, and the typed email stays.
  await invite(p, email, "reviewer");
  await p.getByRole("alert").filter({ hasText: "already waiting" }).waitFor();
  assert.equal(await p.getByLabel("Email").inputValue(), email);
  await p.getByLabel("Email").fill("");

  const row = p.getByRole("listitem").filter({ hasText: email });
  await row.getByRole("button", { name: "Revoke" }).click();
  await p.locator("dialog[open]").getByRole("button", { name: "Revoke" }).click();
  await row.getByText("Revoked").waitFor();
  assert.equal(await row.getByRole("button", { name: "Revoke" }).count(), 0);
  assert.equal(await p.getByLabel("Invitation link").count(), 0, "a revoked link isn't left on screen");
  assert.deepEqual(errors, []);
  await ctx.close();
  console.log("ok  real invite, copy, nothing stored, duplicate refused, revoke");
}

// Full team as owner: manage controls for others, none on your own row.
{
  const { p, ctx, errors } = await open({ before: (page) => mockTeam(page) });
  assert.match(await p.locator("main").innerText(), /4 members/i);
  assert.equal(await p.getByRole("button", { name: "Remove" }).count(), 3);
  assert.equal(await p.getByLabel(/^Role for/).count(), 3);
  assert.doesNotMatch(await p.locator("main").innerText(), /It’s just you/);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/team-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  owner sees manage controls");
}

// Not an owner: list only, invitations never requested.
{
  let asked = 0;
  const { p, ctx } = await open({
    before: async (page) => {
      await mockTeam(page, { ...example("members"), allowed_actions: [] });
      await page.route(`${API}/api/workspace/invitations`, (r) => {
        asked++;
        return r.fulfill(json(403, { error: { code: "FORBIDDEN", message: "no", request_id: "q" } }));
      });
    },
  });
  assert.equal(await p.getByRole("button", { name: "Remove" }).count(), 0);
  assert.equal(await p.getByLabel(/^Role for/).count(), 0);
  assert.equal(await p.getByRole("button", { name: "Create invitation" }).count(), 0);
  assert.equal(asked, 0);
  assert.match(await p.locator("main").innerText(), /Ava Approver/);
  await p.screenshot({ path: `${OUT}/non-owner-desktop.png`, fullPage: true });
  await ctx.close();
  console.log("ok  non-owner has no management controls");
}

// Refusals keep the page and explain.
const CODES = [
  ["ALREADY_MEMBER", 409, /already in the workspace/],
  ["ROLE_ESCALATION_FORBIDDEN", 403, /role you don’t hold/],
  ["FORBIDDEN", 403, /only a workspace owner/i],
];
for (const [code, status, says] of CODES) {
  const { p, ctx } = await open({
    before: async (page) => {
      await mockTeam(page);
      await page.route(`${API}/api/workspace/invitations`, (r) =>
        r.request().method() === "POST" ? r.fulfill(json(status, { error: { code, message: "only a workspace owner can manage members", request_id: "qa-1" } })) : r.fallback(),
      );
    },
  });
  await invite(p, "someone@example.com");
  await p.getByRole("alert").filter({ hasText: says }).waitFor();
  assert.equal(await p.getByLabel("Email").inputValue(), "someone@example.com");
  await ctx.close();
  console.log(`ok  ${code}`);
}

// Change a role, remove someone, and the refusals for each.
{
  const calls = [];
  let refuse = true;
  const { p, ctx } = await open({
    before: async (page) => {
      await page.route(`${API}/api/workspace/members/*`, (r) => {
        calls.push([r.request().method(), r.request().postDataJSON()]);
        if (refuse) return r.fulfill(json(409, { error: { code: "LAST_OWNER_REQUIRED", message: "x", request_id: "qa-2" } }));
        return r.fulfill(json(200, example("members").members[2]));
      });
      await mockTeam(page);
    },
  });
  const select = p.getByLabel("Role for Remy Reviewer");
  await select.selectOption("approver");
  await p.getByRole("alert").filter({ hasText: "at least one owner" }).waitFor();
  await p.waitForLoadState("networkidle");
  assert.equal(await select.inputValue(), "reviewer", "shows the server's role, not a guess");
  refuse = false;
  await select.selectOption("approver");
  await p.waitForFunction(() => !document.querySelector('[role="alert"]'));
  const row = p.getByRole("row").filter({ hasText: "Remy Reviewer" });
  await row.getByRole("button", { name: "Remove" }).click();
  assert.match(await p.locator("dialog[open]").innerText(), /Remove Remy Reviewer\?/i);
  await p.locator("dialog[open]").getByRole("button", { name: "Remove" }).click();
  await p.waitForLoadState("networkidle");
  assert.deepEqual(calls.map((c) => c[0]), ["PATCH", "PATCH", "DELETE"]);
  assert.deepEqual(calls[1][1], { role: "approver" });
  await ctx.close();
  console.log("ok  role change, remove, last-owner refusal");
}

// Failed load, retry and phone width.
{
  let fail = true;
  const { p, ctx } = await open({ before: (page) => page.route(`${API}/api/workspace/members`, (r) => (fail ? r.abort() : r.continue())) });
  assert.match(await p.locator("main").innerText(), /Can’t reach the server/i);
  fail = false;
  await p.getByRole("button", { name: "Try again" }).click();
  await p.getByText(/1 member/i).waitFor();
  await ctx.close();
  const phone = await open({ width: 390, height: 844, before: (page) => mockTeam(page) });
  assert.equal(await phone.p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, "no sideways scroll");
  await phone.p.screenshot({ path: `${OUT}/team-mobile.png`, fullPage: true });
  await phone.ctx.close();
  console.log("ok  failed load recovers; phone width");
}
await b.close();
console.log("team page: all passed");
