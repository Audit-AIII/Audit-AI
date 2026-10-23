// Insights + Scorecard against the REAL backend (both analytics routes are missing today):
// no measured number may appear outside the "Sample data" area; Run evaluation explains it can't run.
// AUDIT_PASSWORD=... node qa/insights-scorecard-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const { AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/login?next=%2Fapp%2Finsights`, { waitUntil: "networkidle" });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/insights", { timeout: 20000 });
await p.waitForSelector(".app-alert--placeholder");
const first = await p.locator(".panel").first().innerText();
assert.match(first, /Not available yet[\s\S]*brand-risk/i);
assert.doesNotMatch(first, /\d+%/, "no number in the real panel");
assert.match(await p.locator(".add-brandline").innerText(), /Lumen Goods/i);
console.log("ok  insights: real panel says not available (no numbers); sample area labelled");

await p.goto(`${WEB}/app/scorecard`, { waitUntil: "networkidle" });
await p.waitForSelector(".add-metrics");
const real = await p.locator(".panel").first().innerText();
assert.match(real, /Catch rate\s*Not measured[\s\S]*Target 85% or more/i);
assert.match(real, /False positives\s*Not measured[\s\S]*Target 15% or less/i);
assert.match(await p.locator(".panel").nth(1).innerText(), /small test set shows testing, not universal accuracy/i);
await p.getByRole("button", { name: "Run evaluation" }).click();
await p.waitForFunction(() => /can’t run evaluations yet/.test(document.body.textContent ?? ""), null, { timeout: 15000 });
console.log("ok  scorecard: 'Not measured' vs targets, limits note, Run evaluation -> clear can't-run message");
assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
