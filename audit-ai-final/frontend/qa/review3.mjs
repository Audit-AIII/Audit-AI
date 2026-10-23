// Captures: check cards, process carousel at each step, login page, header.
import { chromium } from "playwright";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" });
await p.evaluate(() => document.fonts.ready);
await p.screenshot({ path: "qa/out/r3-header.png", clip: { x: 0, y: 0, width: 1182, height: 80 } });

// checks grid fully dealt
await p.evaluate(() => { const g = document.querySelector(".checks__grid"); scrollTo(0, g.getBoundingClientRect().top + scrollY - 90); });
await p.waitForTimeout(2000);
await p.screenshot({ path: "qa/out/r3-checks.png" });
await p.evaluate(() => scrollBy(0, 560));
await p.waitForTimeout(1500);
await p.screenshot({ path: "qa/out/r3-checks2.png" });

// process: step positions
const top = await p.evaluate(() => document.querySelector("#process").getBoundingClientRect().top + scrollY);
const span = await p.evaluate(() => { const s = document.querySelector("#process"); return s.offsetHeight - innerHeight; });
for (const [i, f] of [[1, 0.1], [2, 0.37], [3, 0.62], [4, 0.95]]) {
  await p.evaluate((y) => scrollTo(0, y), top + span * f);
  await p.waitForTimeout(1800);
  await p.screenshot({ path: `qa/out/r3-step${i}.png` });
}

await p.goto("http://localhost:3000/login", { waitUntil: "networkidle" });
await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/r3-login.png" });
await p.fill("#a-email", "demo@audit.ai");
await p.fill("#a-password", "secret1");
await p.click("button[type=submit]");
await p.waitForURL("**/app");
await p.waitForTimeout(800);
await p.screenshot({ path: "qa/out/r3-app.png" });
console.log("ok", errs);
await b.close();
