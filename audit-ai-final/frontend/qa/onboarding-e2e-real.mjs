// Full self-serve onboarding flow against the REAL backend (:8000) and REAL frontend (:3000).
// Sign up -> hero -> Workspace -> upload brand PDF -> Draft (paste) -> Review -> Draft (upload
// .docx) -> Review -> refresh. Also: duplicate sign-up, bad file, backend down, existing seeded
// account. Captures network status codes (port 8000 only) and console errors.
//
// Usage: node qa/onboarding-e2e-real.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";

const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const fx = (f) => path.resolve("qa/fixtures", f);
const email = `e2e-${Date.now()}@example.com`;
const password = "correct horse battery staple";

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1182, height: 937 } });
const p = await ctx.newPage();

const consoleErrors = [];
const net = [];
let currentStep = "";
p.on("console", (m) => m.type() === "error" && consoleErrors.push(`[${currentStep}] ${m.text()}`));
p.on("pageerror", (e) => consoleErrors.push(`[${currentStep}] pageerror: ${e.message}`));
p.on("response", async (r) => {
  const u = new URL(r.url());
  if (u.port !== "8000" || r.request().method() === "OPTIONS") return;
  net.push({ step: currentStep, line: `${r.request().method()} ${u.pathname} -> ${r.status()}` });
});

const step = (s) => {
  currentStep = s;
  console.log(`\n# ${s}`);
};
const shown = (s) => net.filter((n) => n.step === s).forEach((n) => console.log(`   ${n.line}`));
const text = (sel) => p.locator(sel).first().innerText();

step("1) sign up with a brand-new email");
await p.goto(`${WEB}/login?mode=signup`, { waitUntil: "networkidle" });
await p.fill("#a-name", "E2E Tester");
await p.fill("#a-email", email);
await p.fill("#a-password", password);
await p.fill("#a-confirm", password);
await p.fill("#a-brand", "E2E Brand");
await p.click("button[type=submit]");
await p.waitForURL(`${WEB}/`, { timeout: 15000 });
await p.waitForSelector(".account__email", { timeout: 10000 });
assert.equal(await text(".account__email"), email);
shown(currentStep);
console.log(`   ok: on "/" (hero) signed in as "${await text(".account__email")}"`);

step("2) hero -> Workspace -> Sources (no Brand ID field)");
await p.click("a.nav__cta");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.waitForSelector(".approved-count", { timeout: 10000 });
assert.equal(await p.locator("text=Brand ID").count(), 0, "no Brand ID field anywhere");
assert.match(await text(".panel:nth-child(2) .panel__title"), /E2E Brand/i);
assert.equal(await text(".approved-count"), "0");
shown(currentStep);
console.log(`   ok: brand "E2E Brand" picked automatically, 0 approved documents`);

step("3) upload a real brand-fact PDF (approve checked)");
await p.setInputFiles(".upload-form input[type=file]", fx("brand-facts.pdf"));
await p.check(".upload-form .option input");
await p.click(".upload-form button[type=submit]");
await p.waitForSelector(".upload-form .app-alert--ok", { timeout: 30000 });
await p.waitForFunction(() => document.querySelector(".approved-count")?.textContent === "1", { timeout: 15000 });
shown(currentStep);
console.log(`   ok: "${await text(".upload-form .app-alert--ok")}" - approved count now 1`);

step("4) Draft: paste text -> Review");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForFunction(() => /1 approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
await p.fill(".draft__text", "Our product keeps drinks cold for 24 hours and ships worldwide.");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 60000 });
await p.waitForSelector(".problem, .heat__mark", { timeout: 30000 });
const pastedReviewUrl = p.url();
shown(currentStep);
console.log(`   ok: review rendered at ${pastedReviewUrl}`);

step("5) Draft: upload a .docx -> Review");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForSelector(".brand-pill__id");
await p.setInputFiles(".dropzone--small input[type=file]", fx("launch-post.docx"));
assert.equal(await p.locator(".draft__text").isDisabled(), true, "textarea locked while a file is chosen");
await p.fill("input[placeholder^='e.g. Earbuds']", "Launch post");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 60000 });
await p.waitForSelector(".problem, .heat__mark", { timeout: 30000 });
const docxReviewUrl = p.url();
shown(currentStep);
console.log(`   ok: review rendered at ${docxReviewUrl}`);

step("6) refresh the (docx) Review page");
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".problem, .heat__mark", { timeout: 30000 });
shown(currentStep);
console.log(`   ok: review still renders after refresh, url unchanged=${p.url() === docxReviewUrl}`);

step("7) sign out, then duplicate sign-up with the same email");
await p.click(".account__who");
await p.click(".account__menu button");
await p.waitForURL(`${WEB}/`, { timeout: 15000 });
await p.goto(`${WEB}/login?mode=signup`, { waitUntil: "networkidle" });
await p.fill("#a-email", email.toUpperCase());
await p.fill("#a-password", "another password 2");
await p.fill("#a-confirm", "another password 2");
await p.click("button[type=submit]");
await p.waitForSelector(".auth__alert--bad", { timeout: 15000 });
assert.match(await text(".auth__alert--bad"), /already exists/i);
shown(currentStep);
console.log(`   ok (case-insensitive duplicate, UPPERCASE email): "${await text(".auth__alert--bad")}"`);

step("8) sign in as the fresh user again, then try bad files on Draft");
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await p.fill("#a-email", email);
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForSelector(".brand-pill__id");
await p.setInputFiles(".dropzone--small input[type=file]", fx("setup.exe"));
assert.match(await text(".app-alert--bad"), /Only PDF, Word/);
console.log(`   ok (.exe, client-side, no request): "${await text(".app-alert--bad")}"`);
await p.setInputFiles(".dropzone--small input[type=file]", fx("image-only.pdf"));
await p.click("button[type=submit]");
await p.waitForFunction(() => /couldn.t read that file/i.test(document.querySelector(".app-alert--bad")?.textContent ?? ""), { timeout: 30000 });
shown(currentStep);
console.log(`   ok (image-only.pdf, server 422): "${await text(".app-alert--bad")}"`);

step("9) backend unreachable");
await p.route(`${API}/**`, (route) => route.abort("connectionrefused"));
await p.goto(`${WEB}/app/sources`, { waitUntil: "networkidle" });
await p.waitForSelector(".app-alert--bad", { timeout: 15000 });
assert.match(await text(".app-alert--bad"), /couldn.t reach/i);
console.log(`   ok: "${await text(".app-alert--bad")}"`);
await p.unroute(`${API}/**`);

step("10) existing seeded account can still log in (old flow unaffected)");
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", "SeedDemo!2026-not-a-real-secret");
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.waitForSelector(".panel:nth-child(2) .panel__title", { timeout: 10000 });
assert.match(await text(".panel:nth-child(2) .panel__title"), /Lumen Goods/i);
shown(currentStep);
console.log(`   ok: seeded admin signed in, brand "${await text(".panel:nth-child(2) .panel__title")}" picked automatically`);

const real = consoleErrors.filter((e) => !/ERR_CONNECTION_REFUSED|Failed to load resource|status of 4\d\d/.test(e));
console.log(`\nconsole errors (excluding deliberate 4xx/backend-down steps): ${real.length ? real.join("\n  ") : "none"}`);
assert.deepEqual(real, []);
console.log("\nALL ONBOARDING E2E STEPS PASSED");
await b.close();
