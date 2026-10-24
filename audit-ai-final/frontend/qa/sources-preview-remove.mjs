// Sources: chosen-file preview + bin before upload; bin on each document (draft -> real delete via
// DELETE /api/brands/{id}/sources/{sid}; approved -> withdraw, kept under "Withdrawn"); privacy tag
// on one line. Real backend, seeded user. AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/sources-preview-remove.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000", API = "http://localhost:8000";
const EMAIL = process.env.AUDIT_EMAIL ?? "ben@seed.inkloom.demo";
const stamp = Date.now().toString(36);
const TXT = `QA preview ${stamp}\nVerde bottles keep drinks cold for 24 hours.\nPrice: ₹1,299.`;
// smallest valid one-page PDF with a line of text
const PDF = `%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj
4 0 obj<</Length 44>>stream
BT /F1 18 Tf 30 340 Td (Verde fact sheet) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
trailer<</Root 1 0 R>>
%%EOF`;

const login = await (await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: EMAIL, password: process.env.AUDIT_PASSWORD }) })).json();
const H = { Authorization: `Bearer ${login.access_token}` };
const [brand] = await (await fetch(`${API}/api/brands`, { headers: H })).json();
const list = async () => (await fetch(`${API}/api/brands/${brand.id}/sources`, { headers: H })).json();

const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/login?next=%2Fapp%2Fsources`, { waitUntil: "networkidle" });
await p.fill("#a-email", EMAIL); await p.fill("#a-password", process.env.AUDIT_PASSWORD); await p.click("button[type=submit]");
await p.waitForURL("**/app/sources"); await p.waitForSelector(".dropzone");
const file = () => p.locator(".upload-form input[type=file]");

// 1) preview + bin before upload (txt: first lines; pdf: first page in a frame)
await file().setInputFiles({ name: `qa-${stamp}.txt`, mimeType: "text/plain", buffer: Buffer.from(TXT) });
await p.waitForSelector(".fpreview");
assert.equal(await p.locator(".dropzone").count(), 0, "preview replaces the drop area");
assert.match(await p.locator(".fpreview__text").innerText(), /Verde bottles keep drinks cold/);
assert.match(await p.locator(".fpreview__info").innerText(), /qa-.*\.txt[\s\S]*Text file · 1 KB/);
await p.locator(".fpreview").screenshot({ path: "qa/out/sources-preview-txt.png" });
await p.getByRole("button", { name: `Remove qa-${stamp}.txt` }).click();
await p.waitForSelector(".dropzone");
assert.equal(await p.getByRole("button", { name: "Upload" }).isDisabled(), true, "nothing to upload after the bin");
await file().setInputFiles({ name: "facts.pdf", mimeType: "application/pdf", buffer: Buffer.from(PDF) });
await p.waitForSelector(".fpreview__pdf");
await p.waitForFunction(() => document.querySelector(".fpreview__pdf")?.getAttribute("src")?.startsWith("blob:"));
await p.waitForTimeout(800); await p.locator(".fpreview").screenshot({ path: "qa/out/sources-preview-pdf.png" });
await p.getByRole("button", { name: "Remove facts.pdf" }).click();
console.log("ok  preview before upload (txt first lines, pdf first page) and the bin clears the choice");

// 2) upload -> approved; bin = withdraw (confirm), kept under Withdrawn
await file().setInputFiles({ name: `qa-${stamp}.txt`, mimeType: "text/plain", buffer: Buffer.from(TXT) });
await p.fill(".upload-form input.field__input", `QA approved ${stamp}`);
await p.getByRole("button", { name: "Upload" }).click();
await p.waitForSelector(`.rows__item:has-text("QA approved ${stamp}")`);
const approvedRow = p.locator(".rows__item", { hasText: `QA approved ${stamp}` }).first();
// privacy tag: one line, inside the row
const tag = await approvedRow.locator(".privacy").boundingBox(); const row = await approvedRow.boundingBox();
assert.ok(tag.height < 32, `privacy tag on one line (${tag.height}px)`); assert.ok(tag.x + tag.width <= row.x + row.width, "tag inside the row");
const bin = approvedRow.getByRole("button", { name: `Withdraw QA approved ${stamp}` });
await bin.focus(); await p.keyboard.press("Enter");
await p.waitForSelector("dialog.add-dialog[open]");
assert.match(await p.locator("dialog.add-dialog").innerText(), /Withdraw this document\?[\s\S]*stays in the record/i);
await p.keyboard.press("Escape");
assert.equal(await p.evaluate(() => document.activeElement?.getAttribute("aria-label")), `Withdraw QA approved ${stamp}`, "Escape returns focus to the bin");
await p.screenshot({ path: "qa/out/sources-list-1440.png", fullPage: true });
await bin.click(); await p.getByRole("dialog").getByRole("button", { name: "Withdraw" }).click();
await p.waitForSelector(`.app-alert--ok:has-text("is withdrawn")`);
// the list reloads after the notice: wait until it has left the current list (it's under Withdrawn now)
await p.waitForFunction((t) => ![...document.querySelectorAll(".panel .rows:not(.sources-withdrawn .rows) > .rows__item")].some((li) => li.textContent.includes(t)), `QA approved ${stamp}`);
await p.locator(".sources-withdrawn > summary").click();
assert.ok(await p.locator(".sources-withdrawn .rows__item", { hasText: `QA approved ${stamp}` }).isVisible(), "kept under Withdrawn");
assert.equal((await list()).find((s) => s.title === `QA approved ${stamp}`).status, "archived");
console.log("ok  approved document: bin -> confirm -> withdrawn (archived on the server), shown under Withdrawn; Escape returns focus");

// 3) a never-approved document: bin -> confirm -> really deleted
const form = new FormData();
form.append("file", new Blob([TXT], { type: "text/plain" }), "draft.txt"); form.append("title", `QA draft ${stamp}`); form.append("approve", "false"); form.append("sensitivity", "confidential");
const draft = await (await fetch(`${API}/api/brands/${brand.id}/sources`, { method: "POST", headers: H, body: form })).json();
assert.equal(draft.status, "draft");
await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector(`.rows__item:has-text("QA draft ${stamp}")`);
const draftRow = p.locator(".rows__item", { hasText: `QA draft ${stamp}` }).first();
assert.match(await draftRow.locator(".privacy").innerText(), /Private/);
await draftRow.getByRole("button", { name: `Delete QA draft ${stamp}` }).click();
assert.match(await p.locator("dialog.add-dialog").innerText(), /Delete this document\?[\s\S]*never approved/i);
await p.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
await p.waitForSelector(`.app-alert--ok:has-text("is deleted")`);
await p.locator(".rows__item", { hasText: `QA draft ${stamp}` }).waitFor({ state: "detached" });
assert.equal((await list()).some((s) => s.id === draft.id), false, "gone on the server");
console.log("ok  never-approved document: bin -> confirm -> deleted on the server (DELETE route), gone from the list");

// 4) phones: no horizontal scroll
await p.setViewportSize({ width: 390, height: 844 }); await p.reload({ waitUntil: "networkidle" }); await p.waitForTimeout(500);
assert.ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 390, "no horizontal scroll at 390");
await p.screenshot({ path: "qa/out/sources-list-390.png", fullPage: true });
await file().setInputFiles({ name: `qa-${stamp}.txt`, mimeType: "text/plain", buffer: Buffer.from(TXT) });
await p.waitForSelector(".fpreview"); await p.locator(".fpreview").screenshot({ path: "qa/out/sources-preview-390.png" });
assert.ok((await p.evaluate(() => document.documentElement.scrollWidth)) <= 390, "preview fits at 390");
console.log("ok  390px: list and preview fit, no horizontal scroll");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
