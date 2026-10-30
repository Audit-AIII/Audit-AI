// Audit trail on Record and /app/audit: the real log first, then forced edge cases in the browser
// (system actor, unknown action, pages, empty, refusals). Nothing is stored.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/audit-trail.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";

const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("Set AUDIT_PASSWORD");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const OUT = "qa/out/audit-trail";
mkdirSync(OUT, { recursive: true });
const CORS = { "Access-Control-Allow-Origin": WEB, "Access-Control-Expose-Headers": "X-Request-ID" };
const json = (status, body) => ({ status, contentType: "application/json", headers: CORS, body: JSON.stringify(body) });
const example = JSON.parse(readFileSync("qa/fixtures/governance/governance_audit_history.json", "utf8"));

const login = await (
  await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: "asha@seed.inkloom.demo", password }) })
).json();
const auth = { Authorization: `Bearer ${login.access_token}` };
const reviews = await (await fetch(`${API}/api/reviews?limit=100`, { headers: auth })).json();
const base = reviews.find((r) => r.status === "approved") ?? reviews[0];
const itemAudit = `${API}/api/content/${base.content_item_id}/audit*`;
const session = (role = login.role) => ({ email: login.user.email, name: login.user.display_name, token: login.access_token, userId: login.user.id, organisation: login.organisation, role });

const b = await chromium.launch();
const open = async (path, { width = 1182, height = 937, before, role } = {}) => {
  const ctx = await b.newContext({ viewport: { width, height } });
  await ctx.addInitScript((s) => window.localStorage.setItem("audit-ai.session", s), JSON.stringify(session(role)));
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await before?.(p);
  await p.goto(`${WEB}${path}`, { waitUntil: "networkidle" });
  await p.waitForTimeout(400);
  return { p, ctx, errors };
};
const record = `/app/record?id=${base.id}`;

// Real log on Record: every entry the API sends is shown, and the page's existing panels stay.
{
  const real = await (await fetch(`${API}/api/content/${base.content_item_id}/audit?limit=20`, { headers: auth })).json();
  assert.ok(real.items.length > 0, "the seed has history");
  const { p, ctx, errors } = await open(record);
  const panel = p.getByRole("region", { name: "History" });
  await panel.locator(".timeline__item").first().waitFor();
  assert.equal(await panel.locator(".timeline__item").count(), real.items.length);
  const main = await p.locator("main").innerText();
  for (const expected of [/Data Passport/i, /For your files/i, /Who read your text/i]) assert.match(main, expected);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/record-real.png`, fullPage: true });
  await ctx.close();
  console.log(`ok  real history on Record (${real.items.length} entries)`);
}

// Contract example: system actor, before and after, notes, no raw details.
{
  const { p, ctx, errors } = await open(record, { before: (page) => page.route(itemAudit, (r) => r.fulfill(json(200, { ...example, next_cursor: null }))) });
  const panel = p.getByRole("region", { name: "History" });
  await panel.locator(".timeline__item").first().waitFor();
  const text = await panel.innerText();
  for (const expected of [/Approved/, /Ava Approver/, /version 2/, /Routing decision/i, /Price corrected to match/, /Approval refused/i]) assert.match(text, expected);
  assert.doesNotMatch(text, /reason_code|finding_ids|\{/, "raw details never shown");
  assert.ok((await panel.locator(".add-badge").count()) >= 2, "before and after badges");
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/record-example.png`, fullPage: true });
  await ctx.close();
  console.log("ok  example events read plainly");
}

// Unknown action, and paging to the end.
{
  const event = (id, action) => ({ id, actor: null, action, event_type: action, note: null, version_number: null, created_at: "2026-10-28T10:00:00Z", details: null });
  const asked = [];
  const { p, ctx, errors } = await open(record, {
    before: (page) =>
      page.route(itemAudit, (r) => {
        const cursor = new URL(r.request().url()).searchParams.get("cursor");
        asked.push(cursor);
        return r.fulfill(json(200, cursor ? { content_item_id: "x", items: [event("2", "second_thing")], next_cursor: null } : { content_item_id: "x", items: [event("1", "brand.new_action")], next_cursor: "abc+/=" }));
      }),
  });
  const panel = p.getByRole("region", { name: "History" });
  assert.match(await panel.innerText(), /Brand new action/);
  assert.match(await panel.innerText(), /System/, "no actor reads as System");
  await panel.getByRole("button", { name: "Load more" }).click();
  await panel.getByText("Second thing").waitFor();
  assert.equal(await panel.locator(".timeline__item").count(), 2);
  assert.equal(await panel.getByRole("button", { name: "Load more" }).count(), 0, "gone on the last page");
  assert.equal(asked.at(-1), "abc+/=", "the cursor is sent back exactly"); // first page may load twice under dev StrictMode
  assert.deepEqual(errors, []);
  await ctx.close();
  console.log("ok  unknown action and paging");
}

// A bad cursor (422) keeps what's loaded and says why.
{
  const { p, ctx } = await open(record, {
    before: (page) =>
      page.route(itemAudit, (r) => {
        if (!new URL(r.request().url()).searchParams.get("cursor")) return r.fulfill(json(200, { ...example, next_cursor: "bad" }));
        return r.fulfill(json(422, { error: { code: "VALIDATION_ERROR", message: "invalid cursor", request_id: "qa-cursor" } }));
      }),
  });
  const panel = p.getByRole("region", { name: "History" });
  await panel.getByRole("button", { name: "Load more" }).click();
  await panel.getByRole("alert").filter({ hasText: "qa-cursor" }).waitFor();
  assert.equal(await panel.locator(".timeline__item").count(), example.items.length);
  await ctx.close();
  console.log("ok  bad cursor keeps the list");
}

// Empty and failed history on Record.
{
  const empty = await open(record, { before: (page) => page.route(itemAudit, (r) => r.fulfill(json(200, { content_item_id: "x", items: [], next_cursor: null }))) });
  assert.match(await empty.p.getByRole("region", { name: "History" }).innerText(), /No history yet/i);
  await empty.ctx.close();
  let fail = true;
  const failed = await open(record, { before: (page) => page.route(itemAudit, (r) => (fail ? r.abort() : r.continue())) });
  const panel = failed.p.getByRole("region", { name: "History" });
  assert.match(await panel.innerText(), /Can’t reach the server/i);
  fail = false;
  await panel.getByRole("button", { name: "Try again" }).click();
  await panel.locator(".timeline__item").first().waitFor();
  await failed.ctx.close();
  console.log("ok  empty and failed history");
}

// No content item id: says so instead of failing.
{
  const { p, ctx } = await open(record, {
    before: (page) =>
      page.route(`${API}/api/reviews/${base.id}`, (r) => (r.request().method() === "OPTIONS" ? r.continue() : r.fulfill(json(200, { ...base, content_item_id: null })))),
  });
  assert.match(await p.getByRole("region", { name: "History" }).innerText(), /Not provided/);
  await ctx.close();
  console.log("ok  missing content item id");
}

// /app/audit, real data, both sizes.
for (const [name, width, height] of [["audit-desktop", 1182, 937], ["audit-mobile", 390, 844]]) {
  const { p, ctx, errors } = await open("/app/audit", { width, height });
  await p.locator(".timeline__item").first().waitFor();
  assert.match(await p.locator("main").innerText(), /Account registered|Invitation (created|revoked|accepted)/i); // newest first, so earlier QA runs may fill the first page
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth), false, name);
  assert.deepEqual(errors, []);
  await p.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
  await ctx.close();
}
console.log("ok  /app/audit with real data");

// A non-owner gets a calm refusal, and no link to the page.
{
  const { p, ctx } = await open("/app/audit", {
    role: "writer",
    before: (page) =>
      page.route(`${API}/api/workspace/audit*`, (r) => r.fulfill(json(403, { error: { code: "FORBIDDEN", message: "your role cannot read the audit log", request_id: "qa-403" } }))),
  });
  const text = await p.locator("main").innerText();
  assert.match(text, /Only workspace owners can see this/);
  assert.doesNotMatch(text, /Try again/);
  await p.screenshot({ path: `${OUT}/audit-forbidden.png`, fullPage: true });
  await ctx.close();
  console.log("ok  non-owner refusal");
}

await b.close();
console.log("audit trail: all passed");
