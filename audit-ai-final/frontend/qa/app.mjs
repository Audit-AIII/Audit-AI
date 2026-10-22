import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errs = []; p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:3100/login", { waitUntil: "networkidle" });
await p.fill("#a-email", "chahit2006@gmail.com"); await p.fill("#a-password", "secret1"); await p.click("button[type=submit]");
await p.waitForURL("**/app/sources"); await p.evaluate(() => document.fonts.ready);
for (const s of ["sources", "draft", "review", "decide", "record"]) {
  await p.goto(`http://localhost:3100/app/${s}`, { waitUntil: "networkidle" }); await p.waitForTimeout(700);
  await p.screenshot({ path: `qa/out/app-${s}.png` });
}
await p.setViewportSize({ width: 390, height: 844 }); await p.waitForTimeout(500);
await p.goto("http://localhost:3100/app/draft", { waitUntil: "networkidle" }); await p.waitForTimeout(500);
await p.screenshot({ path: "qa/out/app-mobile.png", fullPage: true });
const over = await p.evaluate(() => document.documentElement.scrollWidth - innerWidth);
console.log("mobile overflow", over, "errors", errs);
await b.close();
