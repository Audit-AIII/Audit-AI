// Guidelines page actions against the REAL backend: upload, new version, withdraw (with confirm),
// unsupported / image-only files, and a role that can't manage documents.
// AUDIT_PASSWORD=... node qa/guidelines-live.mjs   (seeded users <role>@seed.inkloom.demo)
import { chromium } from "playwright";
import assert from "node:assert/strict";
import path from "node:path";

const { AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000";
const fx = (f) => path.resolve("qa/fixtures", f);
const b = await chromium.launch();
const errors = [];
async function as(role) {
  const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${WEB}/login?next=%2Fapp%2Fguidelines`, { waitUntil: "networkidle" });
  await p.fill("#a-email", `${role}@seed.inkloom.demo`);
  await p.fill("#a-password", password);
  await p.click("button[type=submit]");
  await p.waitForURL("**/app/guidelines", { timeout: 20000 });
  await p.waitForSelector(".add-doc, .add-state", { timeout: 20000 });
  return p;
}
const alertText = (p) => p.locator(".app-alert").first().innerText();
const net = [];

const p = await as("admin");
p.on("response", (r) => r.url().includes(":8000/api/brands/") && r.request().method() === "POST" && net.push(`${r.request().method()} ${new URL(r.url()).pathname.replace(/[0-9a-f-]{36}/g, "{id}")} ${r.status()}`));
const title = `QA guideline ${Date.now()}`;

// unsupported + image-only
await p.setInputFiles(".add-drop input[type=file] >> nth=0", fx("setup.exe"));
assert.match(await alertText(p), /isn’t a supported file/);
await p.setInputFiles(".add-drop input[type=file] >> nth=0", fx("image-only.pdf"));
await p.click("form button[type=submit]");
await p.waitForFunction(() => /couldn’t find any text/.test(document.querySelector(".app-alert")?.textContent ?? ""), null, { timeout: 30000 });
console.log("ok  .exe rejected before sending; image-only PDF ->", await alertText(p));

// upload
await p.setInputFiles(".add-drop input[type=file] >> nth=0", fx("brand-facts.pdf"));
await p.fill(".field__input >> nth=0", title);
await p.click("form button[type=submit]");
await p.waitForFunction(() => /uploaded and approved/.test(document.querySelector(".app-alert")?.textContent ?? ""), null, { timeout: 30000 });
const row = p.locator(".add-doc", { hasText: title });
await row.waitFor();
assert.match(await row.innerText(), /Version 1[\s\S]*Approved/);
console.log("ok  upload ->", await alertText(p));

// new version
await row.getByRole("button", { name: "↑ Upload new version" }).click();
await p.setInputFiles("dialog[open] input[type=file]", fx("brand-facts.pdf"));
await p.getByRole("button", { name: "Upload version" }).click();
await p.waitForFunction(() => /now has version 2/.test(document.querySelector(".app-alert")?.textContent ?? ""), null, { timeout: 30000 });
await p.waitForFunction((t) => [...document.querySelectorAll(".add-doc")].some((d) => d.textContent.includes(t) && d.textContent.includes("Version 2")), title);
console.log("ok  new version ->", await alertText(p));

// withdraw: reason required, warning shown
await row.getByRole("button", { name: "– Withdraw" }).click();
assert.match(await p.locator("dialog[open]").innerText(), /Approved items that relied on this will be sent back to review/);
assert.equal(await p.getByRole("button", { name: "Withdraw", exact: true }).isDisabled(), true, "needs a reason");
await p.fill("dialog[open] textarea", "QA run: no longer valid");
await p.getByRole("button", { name: "Withdraw", exact: true }).click();
await p.waitForFunction(() => /is withdrawn/.test(document.body.textContent ?? ""), null, { timeout: 30000 });
await p.waitForFunction((t) => [...document.querySelectorAll(".add-doc")].some((d) => d.textContent.includes(t) && d.textContent.includes("Withdrawn")), title);
console.log("ok  withdraw -> Withdrawn; requests:", net.join(" | "));
await p.close();

// reviewer: no manage actions
const r = await as("reviewer");
assert.equal(await r.locator(".add-drop").count(), 0);
assert.equal(await r.locator(".add-doc__actions").count(), 0);
assert.match(await r.locator(".app-alert").first().innerText(), /can’t add or change documents/);
console.log("ok  reviewer sees documents but no upload/approve/withdraw");

assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
