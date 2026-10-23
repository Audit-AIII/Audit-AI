import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready);
await p.evaluate(() => { const l = document.querySelector(".sources__list"); scrollTo(0, l.getBoundingClientRect().top + scrollY - 120); });
await p.waitForTimeout(2000); await p.screenshot({ path: "qa/out/sources-rows.png" });
await p.hover(".sources__row:nth-child(2)"); await p.waitForTimeout(700); await p.screenshot({ path: "qa/out/sources-hover.png" });
await b.close();
