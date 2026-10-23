// Decide + Record against the REAL backend, with several seeded roles.
// Usage: AUDIT_PASSWORD=... AUDIT_BRAND_ID=... node qa/decide-live.mjs
// (seeded users are <role>@seed.inkloom.demo; credentials come from the environment, never commit them)
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password, AUDIT_BRAND_ID: brand } = process.env;
if (!password || !brand) throw new Error("set AUDIT_PASSWORD, AUDIT_BRAND_ID");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";

const b = await chromium.launch();
const pageErrors = [];

async function as(role) {
  const ctx = await b.newContext({ viewport: { width: 1182, height: 937 } });
  const p = await ctx.newPage();
  p.on("pageerror", (e) => pageErrors.push(`${role}: ${e.message}`));
  await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
  await p.fill("#a-email", `${role}@seed.inkloom.demo`);
  await p.fill("#a-password", password);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/sources", { timeout: 15000 });
  await p.evaluate((id) => localStorage.setItem("audit-ai.brand-id", id), brand);
  return { p, ctx };
}
async function submit(p, text) {
  await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
  await p.fill(".draft__text", text);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
  await p.waitForSelector(".problem");
  return new URL(p.url()).searchParams.get("id");
}
const text = (p, sel) => p.locator(sel).first().innerText();
const btn = (p, name) => p.getByRole("button", { name, exact: true });

// 1. Admin approves a (stub) review: needs the "no real check ran" tick first
{
  const { p, ctx } = await as("admin");
  const id = await submit(p, "Live decide test one. The Lumen Bottle keeps drinks cold for 24 hours.");
  await p.click(`a[href="/app/decide?id=${id}"]`);
  await p.waitForSelector(".decisions");
  assert.equal(await btn(p, "Approve").isDisabled(), true, "approve waits for the stub tick");
  assert.match(await text(p, ".decide__why"), /Tick the box/);
  await p.check(".option input");
  assert.equal(await btn(p, "Approve").isDisabled(), false);
  await btn(p, "Approve").click();
  await p.waitForSelector(".app-alert--ok");
  await p.waitForFunction(() => /approved/i.test(document.querySelector(".stage-head__status")?.textContent ?? ""));
  await p.screenshot({ path: "qa/out/live-decide.png" });
  // refresh: outcome comes back from the server
  await p.reload({ waitUntil: "networkidle" });
  await p.waitForSelector(".stage-head__status");
  assert.match(await text(p, ".stage-head__status"), /approved/i);
  assert.match(await text(p, ".app-alert"), /Already decided/i);
  // Record
  await p.goto(`${WEB}/app/record`, { waitUntil: "networkidle" }); // no ?id: uses the last review
  await p.waitForSelector(".timeline");
  const tl = await text(p, ".timeline");
  assert.match(tl, /You[\s\S]*Approved/);
  assert.match(tl, /placeholder check/);
  assert.match(await text(p, ".panel:nth-child(2)"), /wasn’t sent to any AI/i);
  await p.screenshot({ path: "qa/out/live-record.png" });
  // Deciding twice is refused by the server (409), message shown
  const tok = await p.evaluate(() => JSON.parse(localStorage.getItem("audit-ai.session")).token);
  const rev = await (await fetch(`${API}/api/reviews/${id}`, { headers: { Authorization: `Bearer ${tok}` } })).json();
  const again = await fetch(`${API}/api/content-versions/${rev.content_version_id}/approve`, { method: "POST", headers: { Authorization: `Bearer ${tok}` } });
  console.log(`ok  admin: tick → approve → approved after refresh; record shows it; 2nd approve → ${again.status} ${(await again.json()).error.message}`);
  await ctx.close();
}

// Only submitter/admin may POST /api/reviews (403 "missing permission: submit" otherwise),
// so the submitter creates the drafts the other roles decide on.
const drafts = {};
{
  const { p, ctx } = await as("submitter");
  drafts.reviewer = await submit(p, "Live decide test two. It is made from 90% recycled steel.");
  drafts.submitter = await submit(p, "Live decide test three.");
  drafts.approver = await submit(p, "Live decide test four.");
  drafts.brand_manager = await submit(p, "Live decide test five.");
  await ctx.close();
}

// 2. Reviewer sends back with a note; can't approve
let reviewerReview = drafts.reviewer;
{
  const { p, ctx } = await as("reviewer");
  await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
  await p.waitForSelector(".draft__text");
  assert.equal(await p.locator("button[type=submit]").isDisabled(), true, "reviewer can't submit");
  assert.match(await text(p, "form"), /can’t send drafts/);
  await p.goto(`${WEB}/app/decide?id=${reviewerReview}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".decisions");
  assert.equal(await btn(p, "Approve").isDisabled(), true);
  assert.match(await text(p, ".decisions"), /can’t approve/);
  await p.fill(".decide__note", "Please cite the recycled-content source.");
  await btn(p, "Send back for changes").click();
  await p.waitForSelector(".app-alert--ok");
  await p.goto(`${WEB}/app/record?id=${reviewerReview}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".timeline");
  assert.match(await text(p, ".timeline"), /Sent back for changes: “Please cite the recycled-content source\.”/);
  console.log("ok  reviewer: can't submit (explained); approve disabled with reason; send back with note → record shows the note");
  await ctx.close();
}

// 3. Submitter: every decision disabled, with reasons; record of someone else's decision (no local note)
{
  const { p, ctx } = await as("submitter");
  const id = drafts.submitter;
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".decisions");
  for (const n of ["Approve", "Send back for changes", "Reject"]) assert.equal(await btn(p, n).isDisabled(), true, n);
  assert.match(await text(p, ".decisions"), /can’t approve[\s\S]*can’t send it back/);
  await p.goto(`${WEB}/app/record?id=${reviewerReview}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".timeline");
  assert.match(await text(p, ".timeline"), /A reviewer[\s\S]*Sent back for changes/);
  assert.match(await text(p, ".panel:first-child"), /made in another browser/i);
  console.log("ok  submitter: all decisions disabled; sees another user's decision outcome without its note");
  await ctx.close();
}

// 4. Approver vs routing: stub reviews need a brand_manager, so a plain approver is blocked
{
  const { p, ctx } = await as("approver");
  const id = drafts.approver;
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".decisions");
  await p.check(".option input");
  assert.equal(await btn(p, "Approve").isDisabled(), true);
  assert.match(await text(p, ".decisions"), /needs a brand manager/);
  console.log("ok  approver: approve blocked by routing (needs brand manager), reason shown");
  await ctx.close();
}

// 5. Brand manager (the routed role) can approve
{
  const { p, ctx } = await as("brand_manager");
  const id = drafts.brand_manager;
  await p.goto(`${WEB}/app/decide?id=${id}`, { waitUntil: "networkidle" });
  await p.waitForSelector(".decisions");
  await p.check(".option input");
  await btn(p, "Approve").click();
  await p.waitForSelector(".app-alert--ok");
  console.log("ok  brand_manager: approve succeeds");
  await ctx.close();
}

assert.deepEqual(pageErrors, []);
console.log("ok  no page errors");
await b.close();
