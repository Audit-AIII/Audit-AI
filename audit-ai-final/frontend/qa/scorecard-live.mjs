// Scorecard states: live "no evaluation has been run yet" 404 -> empty state; a route-missing 404
// ({"detail":"Not Found"}) -> needs-backend; network error -> error with retry. No number shown.
// AUDIT_EMAIL / AUDIT_PASSWORD env. node qa/scorecard-live.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password } = process.env;
const WEB = "http://localhost:3000", API = "http://localhost:8000";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 } });
const errors = []; p.on("pageerror", (e) => errors.push(e.message));
await p.goto(`${WEB}/login?next=%2Fapp%2Fscorecard`, { waitUntil: "networkidle" });
await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
await p.waitForURL("**/app/scorecard", { timeout: 20000 });
await p.waitForSelector(".add-state--empty");
const empty = await p.locator(".add-state--empty").innerText();
assert.match(empty, /No evaluation yet/i); assert.match(empty, /benchmark results, not live statistics/);
assert.equal(await p.locator(".add-needs").count(), 0); assert.doesNotMatch(await p.locator("main").innerText(), /\d+(\.\d+)?%/);
await p.screenshot({ path: "qa/out/scorecard-empty.png" });
console.log("ok  live 404 'no evaluation has been run yet' -> empty state, no needs-backend, no numbers");
const cors = { "Access-Control-Allow-Origin": WEB };
await p.route(`${API}/api/evaluations/latest`, (r) => r.fulfill({ status: 404, contentType: "application/json", headers: cors, body: '{"detail":"Not Found"}' }));
await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector(".add-needs");
console.log("ok  route-missing 404 -> needs-backend notice");
await p.unroute(`${API}/api/evaluations/latest`);
await p.route(`${API}/api/evaluations/latest`, (r) => r.abort("connectionrefused"));
await p.reload({ waitUntil: "networkidle" }); await p.waitForSelector(".add-state--error");
assert.match(await p.locator(".add-state--error").innerText(), /reach the server/i);
console.log("ok  network error -> error state with retry");
assert.deepEqual(errors, []); console.log("ok  no page errors"); await b.close();
