// Single-user walk-through (DECISIONS.md decision 1) as a seeded owner against the REAL backend:
// Sources -> Draft -> Review -> Decide -> Record -> Queue -> Insights. No screen may mention roles,
// approvers, reviewers, managers or "admin"; no button is disabled by role; Approve and Send back
// work and need an explicit click. Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/single-user-walk.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password } = process.env;
const email = process.env.AUDIT_EMAIL ?? "asha@seed.inkloom.demo";
const WEB = "http://localhost:3000";
const ROLE_WORDS = /\b(admin|approvers?|reviewers?|managers?|legal reviewer|brand manager|your role)\b/i;

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
const clean = async (label) => {
  await p.waitForLoadState("networkidle");
  await p.waitForTimeout(700);
  // visible text of the whole page, plus the open account menu
  const text = await p.evaluate(() => document.body.innerText);
  const hit = text.match(ROLE_WORDS);
  assert.equal(hit, null, `${label}: mentions "${hit?.[0]}"`);
  console.log(`ok  ${label.padEnd(10)} no role / approver / reviewer / admin wording`);
};

await p.goto(`${WEB}/login?next=%2Fapp%2Fsources`, { waitUntil: "networkidle" });
await p.fill("#a-email", email);
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 20000 });
await p.waitForSelector(".approved-count");
await clean("Sources");
assert.equal(await p.locator(".upload-form").count(), 1, "upload form offered");

await p.goto(`${WEB}/app/draft`);
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
await clean("Draft");
await p.fill(".draft__text", "Single-user walk. The Lumen Pods last 30 hours on one charge.");
await p.fill("input[placeholder^='e.g. Earbuds']", "Single-user walk");
assert.equal(await p.locator("button[type=submit]").isDisabled(), false, "Check my draft enabled");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
const id = new URL(p.url()).searchParams.get("id");
await p.waitForSelector(".problem, .app-alert");
await clean("Review");

await p.goto(`${WEB}/app/decide?id=${id}`);
await p.waitForSelector(".decisions");
await clean("Decide");
// No button disabled by role: Send back / Reject enabled; Approve only waits for the explicit
// "no real check ran" tick on a placeholder review (never for a role).
assert.equal(await p.getByRole("button", { name: "Send back for changes" }).isDisabled(), false);
assert.equal(await p.getByRole("button", { name: "Reject" }).isDisabled(), false);
const tick = p.locator(".option input");
if (await tick.count()) {
  assert.equal(await p.getByRole("button", { name: "Approve" }).isDisabled(), true, "placeholder needs the tick");
  await tick.check();
}
assert.equal(await p.getByRole("button", { name: "Approve" }).isDisabled(), false, "Approve enabled after explicit tick");
assert.match(await p.locator(".panel").nth(2).innerText(), /You decide on your own content/);
await p.getByRole("button", { name: "Approve" }).click();
await p.waitForSelector(".app-alert--ok", { timeout: 30000 });
console.log("ok  Decide     Approve worked after an explicit click");

await p.goto(`${WEB}/app/record?id=${id}`);
await p.waitForSelector(".timeline");
await clean("Record");
assert.match(await p.locator(".timeline").innerText(), /You[\s\S]*Approved/);

await p.goto(`${WEB}/app/queue`);
await p.waitForSelector(".add-table, .add-state");
await clean("Queue");
// Send back on another waiting review, from the queue
const row = p.locator("tr", { hasText: "Waiting for your decision" }).first();
const href = await row.locator("a").getAttribute("href");
await p.goto(WEB + href);
await p.waitForSelector(".decisions");
await p.fill(".decide__note", "Please add the source for the battery claim.");
await p.getByRole("button", { name: "Send back for changes" }).click();
await p.waitForSelector(".app-alert--ok", { timeout: 30000 });
console.log("ok  Decide     Send back worked (note kept) on a review opened from the Queue");

await p.goto(`${WEB}/app/insights`);
await p.waitForSelector(".add-insights__basis, .add-state");
await clean("Insights");

// account menu + footer: account name only
await p.click(".account__who");
await p.waitForTimeout(400);
const footer = await p.locator(".app__status-sample").innerText();
assert.doesNotMatch(footer, ROLE_WORDS);
assert.doesNotMatch(await p.locator(".account__menu").innerText(), ROLE_WORDS);
console.log(`ok  account    footer shows "${footer}", menu has no role label`);

assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
