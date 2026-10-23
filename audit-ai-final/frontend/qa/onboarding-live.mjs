// Onboarding walk-through against the REAL backend (:8000) for every route it has today.
// GET /api/brands is filled in from live data only while the backend doesn't have it (qa/lib/brands-shim.mjs).
// Usage: AUDIT_EMAIL=admin@seed.inkloom.demo AUDIT_PASSWORD=... AUDIT_BRAND_ID=... node qa/onboarding-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";
import { shimBrandsList } from "./lib/brands-shim.mjs";

const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, AUDIT_BRAND_ID: brandId } = process.env;
if (!email || !password || !brandId) throw new Error("set AUDIT_EMAIL, AUDIT_PASSWORD, AUDIT_BRAND_ID");
const WEB = "http://localhost:3000";
const API = "http://localhost:8000";
const fx = (f) => path.resolve("qa/fixtures", f);

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const consoleErrors = [];
const net = [];
p.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
p.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
p.on("response", async (r) => {
  const u = new URL(r.url());
  if (u.port !== "8000" || r.request().method() === "OPTIONS") return;
  net.push({ step: currentStep, line: `${r.request().method()} ${u.pathname} ${r.status()}`, ct: r.request().headers()["content-type"] ?? "" });
});
let currentStep = "";
const step = (s) => {
  currentStep = s;
  console.log(`\n# ${s}`);
};
const shown = (s) => net.filter((n) => n.step === s).forEach((n) => console.log(`   ${n.line}${n.ct.startsWith("multipart") ? `   [${n.ct.slice(0, 48)}…]` : ""}`));
const text = (sel) => p.locator(sel).first().innerText();
const brandsShim = await shimBrandsList(p, { brandId, name: "Lumen Goods [seeded]" });

step("7) sign in with the seeded admin");
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await p.fill("#a-email", email);
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 15000 });
await p.waitForSelector(".rows__item, .t-body.panel__note", { timeout: 15000 });
await p.waitForTimeout(800);
assert.equal(await p.locator("text=Brand ID").count(), 0, "no Brand ID field");
assert.match(await text(".panel:nth-child(2) .panel__title"), /Lumen Goods/i);
const before = Number(await text(".approved-count"));
shown(currentStep);
console.log(`   ok: brand picked automatically, ${before} approved documents, no Brand ID field`);

step("3) upload a real PDF");
await p.setInputFiles(".upload-form input[type=file]", fx("brand-facts.pdf"));
assert.match(await text(".upload-form .dropzone__hint"), /brand-facts\.pdf/);
assert.equal(await p.inputValue(".upload-form input.field__input"), "brand facts");
await p.click(".upload-form button[type=submit]");
await p.waitForSelector(".upload-form .app-alert--ok", { timeout: 30000 });
await p.waitForFunction((n) => Number(document.querySelector(".approved-count")?.textContent) === n + 1, before, { timeout: 15000 });
const upload = net.find((n) => n.line.startsWith("POST /api/brands/") && n.line.includes("/sources "));
assert.ok(upload, "upload request seen");
assert.match(upload.ct, /^multipart\/form-data; boundary=/, "multipart with boundary");
assert.match(await text(".rows"), /brand facts[\s\S]*Approved/i);
shown(currentStep);
console.log(`   ok: "${await text(".upload-form .app-alert--ok")}" — approved count ${before} -> ${before + 1}`);
await p.screenshot({ path: "qa/out/onboarding-sources.png" });

step("6) unreadable files on Sources");
await p.setInputFiles(".upload-form input[type=file]", fx("setup.exe"));
assert.match(await text(".upload-form .app-alert--bad"), /Only PDF, Word/);
console.log(`   ok (client-side, no request): "${await text(".upload-form .app-alert--bad")}"`);
await p.setInputFiles(".upload-form input[type=file]", fx("image-only.pdf"));
await p.click(".upload-form button[type=submit]");
await p.waitForSelector(".upload-form .app-alert--bad", { timeout: 30000 });
shown(currentStep);
assert.match(await text(".upload-form .app-alert--bad"), /couldn’t read that file/);
console.log(`   ok: "${await text(".upload-form .app-alert--bad")}"`);

step("4) Draft shows brand + count, paste text");
await p.goto(`${WEB}/app/draft`, { waitUntil: "networkidle" });
await p.waitForFunction(() => /approved document/.test(document.querySelector(".brand-pill__id")?.textContent ?? ""));
console.log(`   brand pill: "${await text(".brand-pill__id")}"`);
assert.match(await text(".brand-pill__id"), new RegExp(`Lumen Goods \\[seeded\\] · ${before + 1} approved document`));
await p.fill(".draft__text", "The Lumen Bottle keeps drinks cold for 24 hours. It is made from 90% recycled steel.");
await p.click("button[type=submit]");
await p.waitForURL("**/app/review?id=*", { timeout: 90000 });
await p.waitForSelector(".problem", { timeout: 30000 });
shown(currentStep);
const reviewUrl = p.url();

step("5) refresh the Review page");
await p.reload({ waitUntil: "networkidle" });
await p.waitForSelector(".problem", { timeout: 30000 });
assert.equal(await p.locator(".heat__mark").count() > 0, true, "draft text still highlighted");
shown(currentStep);
console.log(`   ok: ${await p.locator(".problem").count()} finding(s), text shown, url unchanged=${p.url() === reviewUrl}`);

step("6) backend unreachable");
await p.route(`${API}/**`, (route) => route.abort("connectionrefused"));
await p.goto(`${WEB}/app/sources`, { waitUntil: "networkidle" });
await p.waitForSelector(".app-alert--bad", { timeout: 15000 });
assert.match(await text(".app-alert--bad"), /couldn't reach|couldn’t reach/i);
console.log(`   ok: "${await text(".app-alert--bad")}" + status bar: "${await text(".app__status p")}"`);
await p.unroute(`${API}/**`);

// Console: the backend-down step logs net::ERR_CONNECTION_REFUSED by design; everything else must be clean.
const real = consoleErrors.filter((e) => !/ERR_CONNECTION_REFUSED|Failed to load resource/.test(e));
console.log(`\nconsole errors (excluding the deliberate backend-down step): ${real.length ? real.join("\n  ") : "none"}`);
console.log(`GET /api/brands: real backend ${brandsShim.real}x, filled in from live data ${brandsShim.shimmed}x (route not merged yet)`);
assert.deepEqual(real, []);
await b.close();
