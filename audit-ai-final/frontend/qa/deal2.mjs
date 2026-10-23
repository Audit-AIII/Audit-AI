import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
// grid top at 45% of the viewport, as in the user's screenshot
await p.evaluate(() => { const l = document.querySelector(".checks__grid"); scrollTo(0, l.getBoundingClientRect().top + scrollY - innerHeight * 0.45); });
await p.waitForTimeout(2500); await p.screenshot({ path: "qa/out/deal-mid.png" });
await p.evaluate(() => { const l = document.querySelector(".checks__grid"); scrollTo(0, l.getBoundingClientRect().top + scrollY - innerHeight * 0.15); });
await p.waitForTimeout(2500); await p.screenshot({ path: "qa/out/deal-top.png" });
await b.close();
