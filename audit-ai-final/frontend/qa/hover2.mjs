// Before/after hover pairs for the section micro-interactions + process dot click.
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
const errs = [];
p.on("pageerror", (e) => errs.push(e.message));
await p.goto("http://localhost:3100/", { waitUntil: "networkidle" });
await p.evaluate(() => document.fonts.ready);

const pair = async (name, sel, hoverSel = sel) => {
  await p.evaluate((s) => { const e = document.querySelector(s); scrollTo(0, e.getBoundingClientRect().top + scrollY - 200); }, sel);
  await p.mouse.move(2, 2);
  await p.waitForTimeout(1600);
  const bb = await p.locator(sel).first().boundingBox();
  const clip = { x: Math.max(0, bb.x - 10), y: Math.max(0, bb.y - 10), width: Math.min(1182 - bb.x + 10, bb.width + 20), height: Math.min(700, bb.height + 20) };
  await p.screenshot({ path: `qa/out/h2-${name}-a.png`, clip });
  await p.locator(hoverSel).first().hover();
  await p.waitForTimeout(800);
  await p.screenshot({ path: `qa/out/h2-${name}-b.png`, clip });
};
await pair("wording", ".checks__item:nth-child(2)");
await pair("colours", ".checks__item:nth-child(5)");
await pair("finding", ".finding");
await pair("source", ".sources__row");
await pair("role", ".roles__row");

// dot click → step 3
await p.evaluate(() => scrollTo(0, document.querySelector("#process").getBoundingClientRect().top + scrollY + 10));
await p.waitForTimeout(1500);
await p.click(".process__dots li:nth-child(3) button");
await p.waitForTimeout(2500);
const step = await p.evaluate(() => [...document.querySelectorAll(".process__dots button")].findIndex((x) => x.getAttribute("aria-current") === "step") + 1);
await p.screenshot({ path: "qa/out/h2-dot.png" });

const d = (f) => "data:image/png;base64," + readFileSync(f).toString("base64");
const rows = ["wording", "colours", "finding", "source", "role"].map((n) => `<div style="display:flex;gap:12px;margin:8px;align-items:flex-start"><b style="width:70px;color:#eee">${n}</b><img src="${d(`qa/out/h2-${n}-a.png`)}" style="max-width:600px"><img src="${d(`qa/out/h2-${n}-b.png`)}" style="max-width:600px"></div>`).join("");
const s = await b.newPage({ viewport: { width: 1300, height: 600 } });
await s.setContent(`<body style="margin:0;background:#111;font:12px sans-serif">${rows}</body>`);
await s.screenshot({ path: "qa/out/h2-sheet.png", fullPage: true });
console.log("dot click landed on step", step, "errors:", errs);
await b.close();
