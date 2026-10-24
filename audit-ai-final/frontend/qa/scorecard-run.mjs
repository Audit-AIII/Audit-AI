// Trust Scorecard: real EvaluationOut + Run evaluation. Signs in for real as a seeded user.
// Live: empty state, Run button, keyboard (dialog opens, Escape closes, focus returns), and the REAL
// 409 when no AI provider is configured. Routed (never stored in the database): the running state,
// 429 with Retry disabled, a network error, and the API.md example run rendered after a 201.
// AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node qa/scorecard-run.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const WEB = "http://localhost:3000", API = "http://localhost:8000";
const run = JSON.parse(readFileSync(new URL("./fixtures/evaluation-run.api-example.json", import.meta.url), "utf8"));
const cors = { "Access-Control-Allow-Origin": WEB };
const err = (status, message) => ({ status, contentType: "application/json", headers: cors, body: JSON.stringify({ error: { code: "CONFLICT", message, request_id: "qa" } }) });

const b = await chromium.launch();
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
const shot = async (name) => {
  for (const [w, h] of [[1440, 900], [390, 844]]) {
    await p.setViewportSize({ width: w, height: h });
    await p.waitForTimeout(150);
    const sw = await p.evaluate(() => document.documentElement.scrollWidth);
    assert.ok(sw <= w, `${name} @${w}: horizontal scroll (${sw}px)`);
    await p.screenshot({ path: `qa/out/scorecard-${name}-${w}.png`, fullPage: true });
  }
  await p.setViewportSize({ width: 1440, height: 900 });
};
const headRun = () => p.locator(".stage-head__actions button");

await p.goto(`${WEB}/login?next=%2Fapp%2Fscorecard`, { waitUntil: "networkidle" });
await p.fill("#a-email", "ben@seed.inkloom.demo"); await p.fill("#a-password", process.env.AUDIT_PASSWORD); await p.click("button[type=submit]");
await p.waitForURL("**/app/scorecard", { timeout: 20000 });

// 1) live empty state with both Run buttons
await p.waitForSelector(".add-state--empty");
assert.match(await p.locator(".add-state--empty").innerText(), /No evaluation yet/i);
assert.equal(await p.getByRole("button", { name: "Run evaluation" }).count(), 2, "head + empty state");
await shot("empty");
console.log("ok  live empty state: 'No evaluation yet', Run button in the head and the empty state, no horizontal scroll at 390");

// 2) keyboard: open with Enter, Escape closes, focus back on the button
await headRun().focus(); await p.keyboard.press("Enter");
await p.waitForSelector("dialog.add-dialog[open]");
assert.match(await p.locator("dialog.add-dialog").innerText(), /about 80 labelled test claims[\s\S]*1 to 5 minutes[\s\S]*once\s+every 10 minutes/);
await p.keyboard.press("Escape");
await p.waitForSelector("dialog.add-dialog:not([open])", { state: "attached" });
assert.equal(await p.evaluate(() => document.activeElement?.closest(".stage-head__actions") !== null && document.activeElement?.textContent), "Run evaluation");
console.log("ok  keyboard: Enter opens the dialog, Escape closes it, focus returns to the Run button");

// 3) REAL backend: no provider -> 409, message shown as-is
let posts = 0; p.on("request", (r) => r.url() === `${API}/api/evaluations` && r.method() === "POST" && posts++);
await headRun().click(); await p.getByRole("dialog").getByRole("button", { name: "Run evaluation" }).click();
await p.waitForSelector(".app-alert--bad[role=alert]");
const live409 = await p.locator(".app-alert--bad[role=alert]").innerText();
assert.match(live409, /no AI provider is configured on this server, so the evaluation cannot run; set one up in services\/api\/\.env \(see API\.md\) and try again/);
assert.equal(posts, 1);
assert.equal(await p.getByRole("button", { name: "Retry" }).isEnabled(), true, "nothing ran, so Retry is allowed");
await shot("409");
console.log(`ok  live 409 shown as-is: "${live409.replace(/\s+/g, " ").slice(0, 120)}…"`);

// 4) running (held POST), then 201 with the API.md example -> rendered directly
let release;
await p.route(`${API}/api/evaluations`, async (r) => {
  if (r.request().method() !== "POST") return r.continue();
  await new Promise((res) => (release = res));
  await r.fulfill({ status: 201, contentType: "application/json", headers: cors, body: JSON.stringify(run) });
});
await p.route(`${API}/api/evaluations/latest`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify(run) }));
await p.getByRole("button", { name: "Retry" }).click();
await p.getByRole("dialog").getByRole("button", { name: "Run evaluation" }).click();
await p.waitForFunction(() => /Running\.\.\. this can take up to 5 minutes\. Keep this tab open\./.test(document.querySelector("[aria-live=polite]")?.textContent ?? ""));
assert.equal(await headRun().isDisabled(), true);
await headRun().click({ force: true }).catch(() => {});
assert.equal(await p.locator("dialog.add-dialog[open]").count(), 0, "no second dialog / submit while running");
await shot("running");
release();
await p.waitForSelector("text=What this measures");
const page = await p.locator("main").innerText();
for (const re of [/This tests the claim checker on a small labelled set\. It is not the accuracy of every review\./, /verifier_only/, /Measured on 80 labelled claims/,
  /Sample: 80 labelled claims/, /Development set \(dev\)\s+55\s+100% \(37 of 37\)\s+0% \(0 of 18\)/i, /Held-out set \(heldout\)\s+25\s+100% \(18 of 18\)\s+0% \(0 of 7\)/i,
  /absent fact\s+9\s+100%\s+–/i, /1098 ms/, /3\.64%/, /dataset\.jsonl@0516b9b8ce5b/, /verify-claim-v1/, /Live AI model/])
  assert.match(page, re);
assert.doesNotMatch(page, /\b(pass|fail|passed|failed|target)\b/i, "no verdict, no target");
assert.equal(posts, 2);
await shot("result");
console.log("ok  running state (button disabled, aria-live text, no double submit); 201 run rendered: splits apart, per_check, '–' for null, no verdict");

// 5) scripted run says so
await p.unroute(`${API}/api/evaluations/latest`);
await p.route(`${API}/api/evaluations/latest`, (r) => r.fulfill({ status: 200, contentType: "application/json", headers: cors, body: JSON.stringify({ ...run, provider_mode: "scripted" }) }));
await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector("text=What this measures");
assert.match(await p.locator("main").innerText(), /Offline test run, not a real model\./);
console.log("ok  provider_mode scripted -> 'Offline test run, not a real model.'");

// 6) 429 -> message as-is, Retry disabled; network error -> the agreed text + Check for a result
await p.unroute(`${API}/api/evaluations`);
await p.route(`${API}/api/evaluations`, (r) => (r.request().method() === "POST" ? r.fulfill(err(429, "an evaluation can be run once every 10 minutes; try again later")) : r.continue()));
await headRun().click(); await p.getByRole("dialog").getByRole("button", { name: "Run evaluation" }).click();
await p.waitForSelector(".app-alert--bad[role=alert]");
assert.match(await p.locator(".app-alert--bad[role=alert]").innerText(), /an evaluation can be run once every 10 minutes; try again later/);
assert.equal(await p.getByRole("button", { name: "Retry" }).isDisabled(), true);
assert.equal(await headRun().isDisabled(), true);
await shot("429");
console.log("ok  429 shown as-is; Retry and Run disabled until the interval has passed");
await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector("text=What this measures");
await p.unroute(`${API}/api/evaluations`);
await p.route(`${API}/api/evaluations`, (r) => (r.request().method() === "POST" ? r.abort("connectionreset") : r.continue()));
await headRun().click(); await p.getByRole("dialog").getByRole("button", { name: "Run evaluation" }).click();
await p.waitForSelector(".app-alert--bad[role=alert]");
assert.match(await p.locator(".app-alert--bad[role=alert]").innerText(), /Could not reach the server\. The run may still be going; check again in a few minutes\./);
assert.equal(await p.getByRole("button", { name: "Check for a result" }).isEnabled(), true);
console.log("ok  network error: agreed text, 'Check for a result' offered");

assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
