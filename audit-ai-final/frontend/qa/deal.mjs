import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
const g = await p.evaluate(() => { const l = document.querySelector(".checks__grid"); const r = l.getBoundingClientRect(); return { top: r.top + scrollY, h: r.height }; });
const start = g.top - 937, end = g.top + g.h - 937 * 0.45;
console.log("deal scroll distance px:", Math.round(end - start));
for (const f of [0.25, 0.5, 0.75, 1]) { await p.evaluate((y) => scrollTo(0, y), start + (end - start) * f); await p.waitForTimeout(2500); await p.screenshot({ path: `qa/out/deal-${f * 100}.png` }); }
await b.close();
