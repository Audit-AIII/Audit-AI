import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(1500);
await p.screenshot({ path: "qa/out/beach-hero.png" });
const at = async (sel, off, name) => { await p.evaluate(([s, o]) => scrollTo(0, document.querySelectorAll(s)[0].getBoundingClientRect().top + scrollY - o), [sel, off]); await p.waitForTimeout(2200); await p.screenshot({ path: `qa/out/${name}.png` }); };
await at(".shoreline", 450, "beach-shore");
await at("#faq", 120, "beach-faq");
await b.close();
