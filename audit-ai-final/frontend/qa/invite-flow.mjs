// Invitation and workspace switch against the REAL backend: a brand-new person opens a link, signs up,
// accepts and lands in the team workspace, then switches back with nothing carried over. Cases the
// real flow can't reach (expired link) are forced in the browser. Removes the member it adds; the
// throwaway qa-* user stays in the local database.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/invite-flow.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/invite-flow";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });

const signInApi = async (email) =>
  (await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) })).json();
const asha = await signInApi("asha@seed.inkloom.demo");
const ben = await signInApi("ben@seed.inkloom.demo");
const auth = (l) => ({ Authorization: `Bearer ${l.access_token}`, "Content-Type": "application/json" });
const sessionOf = (l) => ({ email: l.user.email, name: l.user.display_name, token: l.access_token, userId: l.user.id, organisation: l.organisation, role: l.role });
const invite = async (email, role = "reviewer") => {
  const res = await (await fetch(`${API}/api/workspace/invitations`, { method: "POST", headers: auth(asha), body: JSON.stringify({ email, role }) })).json();
  assert.ok(res.accept_path, JSON.stringify(res));
  return res;
};

const b = await chromium.launch();
const context = async (who, viewport = { width: 1182, height: 937 }) => {
  const ctx = await b.newContext({ viewport });
  if (who) await ctx.addInitScript((s) => window.localStorage.getItem("audit-ai.session") || window.localStorage.setItem("audit-ai.session", s), JSON.stringify(sessionOf(who)));
  return ctx;
};
const settle = async (p) => {
  await p.waitForLoadState("networkidle");
  await p.waitForTimeout(400);
};

// A brand-new person: link, sign up, come back, accept, workspace.
const newEmail = `qa-invite-${Date.now()}@example.com`;
const { accept_path: path } = await invite(newEmail);
const ctx = await context(null);
const p = await ctx.newPage();
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}${path}`);
await settle(p);
assert.match(await p.locator("main").innerText(), /You’re invited/i);
assert.equal(await p.getByRole("button", { name: "Accept invitation" }).count(), 0, "signed out: nothing to accept yet");
await p.screenshot({ path: `${OUT}/signed-out-desktop.png`, fullPage: true });

await p.getByRole("link", { name: "Create an account" }).click();
await p.waitForURL("**/login?mode=signup*");
await p.fill("#a-email", newEmail);
await p.fill("#a-password", password);
await p.fill("#a-confirm", password);
await p.click("button[type=submit]");
await p.waitForURL("**/invite/accept?token=*", { timeout: 30000 });
await settle(p);
assert.match(await p.locator("main").innerText(), new RegExp(newEmail));
await p.screenshot({ path: `${OUT}/signed-in-desktop.png`, fullPage: true });
await p.evaluate(() => localStorage.setItem("audit-ai.active-brand", "from-old-workspace"));

await p.getByRole("button", { name: "Accept invitation" }).click();
await p.getByRole("button", { name: /Open the workspace/ }).waitFor();
const joined = await p.locator("main").innerText();
assert.match(joined, /\[SEEDED\] Asha’s account|\[SEEDED\] Asha's account/);
assert.match(joined, /Reviewer/);
await p.screenshot({ path: `${OUT}/joined-desktop.png`, fullPage: true });
const after = await p.evaluate(() => ({ brand: localStorage.getItem("audit-ai.active-brand"), session: JSON.parse(localStorage.getItem("audit-ai.session")) }));
assert.equal(after.brand, null, "the old workspace's brand is forgotten");
assert.equal(after.session.organisation.id, asha.organisation.id);
assert.equal(after.session.role, "reviewer");
assert.equal(after.session.workspace.is_personal, true, "workspace kept from the response");
await p.getByRole("button", { name: /Open the workspace/ }).click();
await p.waitForURL("**/app/**");
await settle(p);
console.log("ok  new person: link, sign up, accept, workspace");

// Team view as a reviewer: the same Team page, without management.
await p.goto(`${WEB}/app/team`);
await settle(p);
assert.equal(await p.getByRole("button", { name: "Create invitation" }).count(), 0, "reviewers can't invite");
assert.match(await p.locator("main").innerText(), /2 members/i);
console.log("ok  reviewer sees the team read-only");

// is_personal stays true after someone joins, so the page must go by who's really here.
{
  const list = await (await fetch(`${API}/api/reviews?limit=100`, { headers: auth(asha) })).json();
  const open = list.find((r) => r.status === "needs_human_review");
  assert.equal(open.workspace.is_personal, true, "the flag this guards against");
  await p.goto(`${WEB}/app/decide?id=${open.id}`);
  await p.waitForFunction(() => /Author/i.test(document.querySelector(".add-gov")?.textContent ?? ""));
  const bar = await p.locator(".add-gov").innerText();
  assert.match(bar, /Asha/);
  assert.doesNotMatch(bar, /you are the only member/);
  await p.screenshot({ path: `${OUT}/decide-joined-desktop.png`, fullPage: true });
  await p.goto(`${WEB}/app/review?id=${open.id}`);
  await p.getByText("Everyone in this workspace can see these.").waitFor();
  console.log("ok  a workspace someone joined isn't treated as solo");
}

// The same link can't be used twice.
await p.goto(`${WEB}${path}`);
await settle(p);
await p.getByRole("button", { name: "Accept invitation" }).click();
await p.getByRole("alert").filter({ hasText: "already been accepted" }).waitFor();
assert.equal(await p.getByRole("button", { name: "Accept invitation" }).count(), 0, "no retry on a used link");
console.log("ok  used link is refused");

// Switcher: two workspaces, switch to their own, data doesn't carry over.
await p.goto(`${WEB}/app/queue`);
await settle(p);
await p.evaluate(() => {
  localStorage.setItem("audit-ai.last-review", "from-team-workspace");
  localStorage.setItem("audit-ai.review-text.x", "secret draft");
});
const teamRows = await p.locator(".add-table tbody tr").count();
assert.ok(teamRows > 0, "team reviews are visible");
await p.locator(".account__who").click();
const switcher = p.getByRole("navigation", { name: "Switch workspace" });
await switcher.waitFor();
const switcherText = await switcher.innerText();
assert.match(switcherText, /✓/, "marks the current one");
await p.screenshot({ path: `${OUT}/switcher-desktop.png` });
await switcher.getByRole("button").first().click();
await p.waitForURL("**/app/**");
await settle(p);
const switched = await p.evaluate(() => ({
  last: localStorage.getItem("audit-ai.last-review"),
  text: localStorage.getItem("audit-ai.review-text.x"),
  org: JSON.parse(localStorage.getItem("audit-ai.session")).organisation.id,
  role: JSON.parse(localStorage.getItem("audit-ai.session")).role,
}));
assert.equal(switched.last, null);
assert.equal(switched.text, null);
assert.notEqual(switched.org, asha.organisation.id);
assert.equal(switched.role, "owner", "their own workspace");
await p.goto(`${WEB}/app/queue`);
await settle(p);
assert.equal(await p.locator(".add-table tbody tr").count(), 0, "no team reviews in their own workspace");
console.log("ok  switching forgets the old workspace and shows only the new one");
assert.deepEqual(errors, []);
await ctx.close();

// One workspace: no switcher (Ben is in only his own).
{
  const c = await context(ben);
  const page = await c.newPage();
  await page.goto(`${WEB}/app/queue`);
  await settle(page);
  await page.locator(".account__who").click();
  await page.waitForTimeout(600);
  assert.equal(await page.getByRole("navigation", { name: "Switch workspace" }).count(), 0);
  await c.close();
  console.log("ok  no switcher with one workspace");
}

// Wrong person: says so, signing out keeps the invitation page.
{
  const wrong = await invite(`qa-wrong-${Date.now()}@example.com`);
  const c = await context(null);
  const page = await c.newPage();
  await page.goto(`${WEB}/login`);
  await page.evaluate((s) => localStorage.setItem("audit-ai.session", s), JSON.stringify(sessionOf(ben)));
  await page.goto(`${WEB}${wrong.accept_path}`);
  await settle(page);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByRole("alert").filter({ hasText: "different email" }).waitFor();
  await page.screenshot({ path: `${OUT}/wrong-email-desktop.png`, fullPage: true });
  await page.getByRole("button", { name: "Sign out and use that email" }).click();
  await page.getByRole("link", { name: "Sign in" }).waitFor();
  assert.ok(page.url().includes("/invite/accept?token="), "still on the invitation");
  await c.close();
  await fetch(`${API}/api/workspace/invitations/${wrong.invitation.id}/revoke`, { method: "POST", headers: auth(asha) });
  console.log("ok  wrong email is refused with a way forward");
}

// Revoked link, for real.
{
  const gone = await invite(`qa-gone-${Date.now()}@example.com`);
  await fetch(`${API}/api/workspace/invitations/${gone.invitation.id}/revoke`, { method: "POST", headers: auth(asha) });
  const c = await context(ben);
  const page = await c.newPage();
  await page.goto(`${WEB}${gone.accept_path}`);
  await settle(page);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByRole("alert").filter({ hasText: "withdrawn" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Accept invitation" }).count(), 0);
  await c.close();
  console.log("ok  revoked link");
}

// Forced: expired, not found, network failure with a working retry, and a missing token.
for (const [code, status, message, says] of [
  ["INVITE_EXPIRED", 409, "this invitation has expired; ask for a new one", /expired/],
  ["NOT_FOUND", 404, "invitation not found", /not found/i],
]) {
  const c = await context(ben);
  const page = await c.newPage();
  await page.route(`${API}/api/invitations/accept`, (r) => r.fulfill(json(status, { error: { code, message, request_id: "qa" } })));
  await page.goto(`${WEB}/invite/accept?token=abc`);
  await settle(page);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByRole("alert").filter({ hasText: says }).waitFor();
  await c.close();
  console.log(`ok  ${code}`);
}
{
  const c = await context(ben);
  const page = await c.newPage();
  await page.route(`${API}/api/invitations/accept`, (r) => r.abort());
  await page.goto(`${WEB}/invite/accept?token=abc`);
  await settle(page);
  await page.getByRole("button", { name: "Accept invitation" }).click();
  await page.getByRole("alert").filter({ hasText: "couldn't reach" }).waitFor();
  assert.equal(await page.getByRole("button", { name: "Accept invitation" }).count(), 1, "can try again");
  await page.goto(`${WEB}/invite/accept`);
  await settle(page);
  assert.match(await page.locator("main").innerText(), /link is incomplete/);
  await c.close();
  console.log("ok  network failure and missing token");
}

// A bad ?next= never leaves the site, and sign-in returns to the invitation.
{
  const c = await context(null);
  const page = await c.newPage();
  await page.goto(`${WEB}/login?next=${encodeURIComponent("https://evil.example")}`);
  await settle(page);
  assert.ok(!(await page.getByRole("link", { name: "Create an account" }).getAttribute("href")).includes("evil"), "a bad next isn't carried");
  await page.goto(`${WEB}/invite/accept?token=abc`);
  await settle(page);
  await page.getByRole("link", { name: "Sign in" }).click();
  await page.waitForURL("**/login?next=*");
  await page.fill("#a-email", "ben@seed.inkloom.demo");
  await page.fill("#a-password", password);
  await page.click("button[type=submit]");
  await page.waitForURL("**/invite/accept?token=abc", { timeout: 30000 });
  await c.close();
  console.log("ok  next is safe, and sign-in returns to the invitation");
}

// Phone width.
{
  const c = await context(null, { width: 390, height: 844 });
  const page = await c.newPage();
  await page.goto(`${WEB}/invite/accept?token=abc`);
  await settle(page);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false);
  await page.screenshot({ path: `${OUT}/signed-out-mobile.png`, fullPage: true });
  await c.close();
  console.log("ok  phone width");
}

// Clean up the member this run added.
const members = await (await fetch(`${API}/api/workspace/members`, { headers: auth(asha) })).json();
for (const m of members.members.filter((x) => !x.is_you)) await fetch(`${API}/api/workspace/members/${m.user.id}`, { method: "DELETE", headers: auth(asha) });
await b.close();
console.log("invite flow: all passed");
