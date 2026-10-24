// Demo rehearsal on the real app: frontend http://localhost:3001, backend http://localhost:8001.
// Logs in through the UI as the seeded user, opens the seeded reviews used in the demo script and
// checks the claim, verdict wording, evidence quote and correction are on screen. Seeded reviews
// were produced by the real engine with the offline scripted provider (model "scripted/demo-v1").
// Usage (from services/verification): AUDIT_PASSWORD=<seeded demo password> node demo/demo-check.mjs <screenshot dir>
// Needs Microsoft Edge (Playwright channel "msedge") and the frontend's node_modules.
import { chromium } from "../../../audit-ai-final/frontend/node_modules/playwright/index.mjs";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const WEB = "http://localhost:3001";
const API = "http://127.0.0.1:8001";
const [out] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const pass = (m) => console.log(`PASS  ${m}`);

const login = await (await fetch(`${API}/api/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "asha@seed.inkloom.demo", password: process.env.AUDIT_PASSWORD }) })).json();
const listing = await (await fetch(`${API}/api/reviews`, { headers: { Authorization: `Bearer ${login.access_token}` } })).json();
const reviews = listing.reviews ?? listing;
const byTitle = (t) => reviews.find((r) => (r.title ?? "").includes(t));

const b = await chromium.launch({ channel: "msedge" });
const run = async () => {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(`${WEB}/login`, { waitUntil: "networkidle" });
  await p.fill("#a-email", "asha@seed.inkloom.demo");
  await p.fill("#a-password", process.env.AUDIT_PASSWORD);
  await p.click("button[type=submit]");
  await p.waitForURL((u) => u.pathname.startsWith("/app"), { timeout: 20000 });
  pass("signed in through the UI as the seeded user");

  // The UI uses plain labels: "Matches" (supported), "Doesn't match" (contradicted),
  // "Not proven yet" (unverified); the evidence panel shows the selected finding.
  const scenes = [
    { title: "Lumen Pods launch post", shot: "1-contradicted-with-correction.png",
      expect: ["Lumen Pods offer up to 24 hours of playback per charge.", "Doesn’t match", "up to 12 hours of playback per charge",
               "Checked by fallback · scripted/demo-v1"] },
    { title: "Lumen Pods summer ad", shot: "2-unverified-and-contradicted.png",
      expect: ["Lumen Pods are the best-selling earbuds in Europe.", "Not proven yet", "Not suitable for swimming."] },
    { title: "Lumen Pods product page", shot: "3-supported-approved.png", click: "Lumen Pods come with a 2-year warranty.",
      expect: ["APPROVED", "Matches", "Warranty: 2 years."] },
  ];
  for (const scene of scenes) {
    const r = byTitle(scene.title);
    assert.ok(r, `seeded review "${scene.title}" exists`);
    await p.goto(`${WEB}/app/review?id=${r.id}`, { waitUntil: "networkidle" });
    await p.waitForTimeout(800);
    if (scene.click) {
      await p.locator("main").getByText(scene.click, { exact: false }).last().click();
      await p.waitForTimeout(500);
    }
    const text = await p.locator("main").innerText();
    for (const e of scene.expect) assert.ok(text.includes(e), `${scene.title}: shows "${e}"`);
    await p.screenshot({ path: `${out}/${scene.shot}`, fullPage: true });
    pass(`${scene.title}: ${scene.expect.map((e) => JSON.stringify(e.slice(0, 40))).join(", ")} (${scene.shot})`);
  }
  const launch = byTitle("Lumen Pods launch post");
  await p.goto(`${WEB}/app/decide?id=${launch.id}`, { waitUntil: "networkidle" });
  await p.screenshot({ path: `${out}/4-decide.png`, fullPage: true });
  pass("decide page opens for the review (human makes the call)");
  await p.goto(`${WEB}/app/queue`, { waitUntil: "networkidle" });
  await p.screenshot({ path: `${out}/5-queue.png`, fullPage: true });
  pass("review queue opens");
  assert.deepEqual(errors, [], "no page errors");
  pass("no page errors during the walk-through");
  await ctx.close();
};
try {
  await Promise.race([run(), new Promise((_, reject) => setTimeout(() => reject(new Error("timeout")), 120000))]);
} finally {
  await Promise.race([b.close(), new Promise((r) => setTimeout(r, 5000))]);
}
process.exit(0);
