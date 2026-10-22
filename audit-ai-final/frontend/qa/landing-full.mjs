import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready);
const names = process.argv.slice(2);
for (const [i, sel] of names.entries()) {
  await p.evaluate((s) => { const e = document.querySelector(s); scrollTo(0, e.getBoundingClientRect().top + scrollY - 70); }, sel);
  await p.waitForTimeout(1600);
  await p.screenshot({ path: `qa/out/land-${i}.png` });
}
await b.close();
