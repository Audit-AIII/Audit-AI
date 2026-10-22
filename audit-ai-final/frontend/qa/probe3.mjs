import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("https://relevovinco.com", { waitUntil: "networkidle" }); await p.waitForTimeout(1000);
for (const y of [700, 1300, 1900, 2500, 3100]) {
  await p.evaluate((y) => window.scrollTo(0, y), y); await p.waitForTimeout(1500);
  await p.screenshot({ path: `qa/out/ref-y${y}.png` });
}
const info = await p.evaluate(() => [...document.querySelectorAll("#craft *")].slice(0, 40).map(e => { const cs = getComputedStyle(e); return `${e.tagName}.${e.className} "${(e.childElementCount?"":e.textContent).trim().slice(0,30)}" t=${cs.transform} op=${cs.opacity} bs=${cs.boxShadow.slice(0,60)}`; }));
console.log(info.join("\n"));
await b.close();
