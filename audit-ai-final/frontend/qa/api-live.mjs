// Browser flow against the REAL backend (no mocks). Frontend on :3000, API on :8000.
// Usage: AUDIT_EMAIL=... AUDIT_PASSWORD=... AUDIT_BRAND_ID=... node qa/api-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, AUDIT_BRAND_ID: brand } = process.env;
if (!email || !password || !brand) throw new Error("set AUDIT_EMAIL, AUDIT_PASSWORD, AUDIT_BRAND_ID");
const WEB = "http://localhost:3000";

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const pageErrors = [];
const failed = [];
p.on("pageerror", (e) => pageErrors.push(e.message));
p.on("requestfailed", (r) => r.url().includes(":8000") && failed.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`));
const text = (sel) => p.locator(sel).first().innerText();

// Sign in (wrong password first)
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await p.fill("#a-email", email);
await p.fill("#a-password", "not-the-password");
await p.click("button[type=submit]");
await p.waitForSelector(".auth__alert--bad");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.waitForTimeout(2500);
console.log("ok  sign in; status bar:", await text(".app__status-sample"));

// Sources
await p.fill(".brand-form input", brand);
await p.click(".brand-form button");
await p.waitForSelector(".rows__item", { timeout: 15000 });
console.log("ok  sources:", (await p.locator(".rows__title").allInnerTexts()).join(" | "));

// Draft -> review
const draft = "\u{1F3A7} The Lumen Bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled steel.";
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.fill(".draft__text", draft);
await p.fill("input[placeholder^='e.g. Earbuds']", "Live e2e check");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
await p.waitForSelector(".problem", { timeout: 30000 });
const url = p.url();
const stub = await p.locator(".app-alert--placeholder").count();
console.log(`ok  submitted -> ${url.split("?")[1]}; headline="${await text(".stage-head__status")}" placeholder=${stub ? "yes" : "no"}`);
if (stub) {
  assert.equal(await p.locator(".chip--contradicted, .chip--unverified, .chip--supported").count(), 0, "stub must not show verdict chips");
  // the placeholder highlight covers exactly the submitted text (code point span 0..end)
  assert.equal(await text(".heat__mark"), draft);
}
await p.screenshot({ path: "qa/out/live-review.png" });

// Refresh keeps it
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".problem", { timeout: 30000 });
assert.equal(p.url(), url);
console.log("ok  refresh: findings still shown:", await p.locator(".problem").count());

// Unknown review id -> 404 message with request id
await p.goto(`${WEB}/app/review?id=00000000-0000-4000-8000-000000000000`, { waitUntil: "networkidle" });
await p.waitForSelector(".app-alert--bad");
console.log("ok  404:", (await text(".app-empty")).replace(/\s+/g, " ").slice(0, 140));

// Expired/invalid token -> central 401 -> sign-in page
await p.evaluate(() => {
  const s = JSON.parse(localStorage.getItem("audit-ai.session"));
  localStorage.setItem("audit-ai.session", JSON.stringify({ ...s, token: "expired-token" }));
});
await p.goto(`${WEB}/app/sources`, { waitUntil: "networkidle" });
await p.waitForURL("**/login?expired=1", { timeout: 15000 });
console.log("ok  401 -> /login?expired=1, session cleared:", (await p.evaluate(() => localStorage.getItem("audit-ai.session"))) === null);

assert.deepEqual(pageErrors, [], "page errors");
assert.deepEqual(failed, [], "network/CORS failures");
console.log("ok  no page errors, no CORS/network failures");
await b.close();
