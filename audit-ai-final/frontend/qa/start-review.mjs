// "Start a review" goes to the Draft stage when signed in, and through sign-in back to it when not.
// Live backend. Usage: AUDIT_PASSWORD=... node qa/start-review.mjs
import { chromium } from "playwright";
import assert from "node:assert/strict";

const WEB = "http://localhost:3000";
const { AUDIT_PASSWORD: password } = process.env;
if (!password) throw new Error("set AUDIT_PASSWORD");
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errors = [];
p.on("pageerror", (e) => errors.push(e.message));
const settle = () => p.waitForFunction(() => getComputedStyle(document.querySelector(".sandwave")).visibility === "hidden", null, { timeout: 15000 });

// 1. Signed out: hero button -> sign in -> lands on Draft (not Sources)
await p.goto(WEB, { waitUntil: "networkidle" });
assert.equal(await p.locator("#top .hero__actions a.btn").getAttribute("href"), "/login?next=%2Fapp%2Fdraft");
await p.click("#top .hero__actions a.btn");
await p.waitForURL("**/login?next=*");
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/draft", { timeout: 15000 });
await settle();
console.log("ok  signed out: Start a review -> sign in -> /app/draft");

// 2. Signed in: every Start-a-review button goes straight to Draft, no sign-in page
await p.goto(WEB, { waitUntil: "networkidle" });
for (const sel of ["#top .hero__actions a.btn", ".roles__actions a.btn", "#contact a.btn"]) {
  assert.equal(await p.locator(sel).first().getAttribute("href"), "/app/draft", sel);
}
await p.click("#top .hero__actions a.btn");
await p.waitForURL("**/app/draft", { timeout: 15000 });
await settle();
assert.ok(!p.url().includes("/login"));
console.log("ok  signed in: Start a review -> /app/draft directly (all buttons)");

// 3. Signed in + an old /login link -> skips the form
await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
await p.waitForURL("**/app", { timeout: 15000 }).catch(() => {});
await p.waitForURL("**/app/sources", { timeout: 15000 });
console.log("ok  signed in + /login -> straight to the workspace");

// 4. Unsafe ?next= is ignored (no open redirect)
await p.evaluate(() => localStorage.removeItem("audit-ai.session"));
await p.goto(`${WEB}/login?next=https://evil.example`, { waitUntil: "networkidle" });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/sources", { timeout: 15000 });
console.log("ok  ?next=https://evil.example ignored -> /app");

// 5. Signed out, open a workspace page directly -> sign in -> back to that page
await p.evaluate(() => localStorage.removeItem("audit-ai.session"));
await p.goto(`${WEB}/app/record`, { waitUntil: "networkidle" });
await p.waitForURL("**/login?next=%2Fapp%2Frecord", { timeout: 15000 });
await p.fill("#a-email", "admin@seed.inkloom.demo");
await p.fill("#a-password", password);
await p.click("button[type=submit]");
await p.waitForURL("**/app/record", { timeout: 15000 });
await settle();
console.log("ok  signed out on /app/record -> sign in -> back to /app/record");

assert.deepEqual(errors, []);
console.log("ok  no page errors");
await b.close();
