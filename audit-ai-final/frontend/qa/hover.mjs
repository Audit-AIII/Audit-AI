// Captures each hover/press micro-interaction: node qa/hover.mjs → qa/out/hover-*.png
import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("http://localhost:3000/", { waitUntil: "networkidle" }); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(1500);
const shot = async (name, sel, pad = 24, act) => {
  const el = p.locator(sel).first(); const bb = await el.boundingBox();
  const clip = { x: Math.max(0, bb.x - pad), y: Math.max(0, bb.y - pad), width: bb.width + pad * 2, height: bb.height + pad * 2 };
  await p.mouse.move(5, 500); await p.waitForTimeout(700); await p.screenshot({ path: `qa/out/hover-${name}-a.png`, clip });
  await el.hover(); if (act) await p.mouse.down(); await p.waitForTimeout(700);
  await p.screenshot({ path: `qa/out/hover-${name}-b.png`, clip }); if (act) await p.mouse.up();
};
await shot("box", ".hero__channel");
await shot("cut", ".hero__line--cut .hero__word");
await shot("brand", ".nav__brand", 12);
await shot("btn", ".hero__actions .btn", 20);
await shot("btn-press", ".hero__actions .btn", 20, true);
await shot("link", ".link-arrow", 12);
// pointer light: cursor far right vs far left
await p.mouse.move(1150, 850); await p.waitForTimeout(2500); await p.screenshot({ path: "qa/out/hover-light-right.png" });
await p.mouse.move(30, 100); await p.waitForTimeout(2500); await p.screenshot({ path: "qa/out/hover-light-left.png" });
// stitch pairs
const fs = await import("node:fs");
const d = (f) => "data:image/png;base64," + fs.readFileSync(f).toString("base64");
const rows = ["box", "cut", "brand", "btn", "btn-press", "link"].map((n) => `<div style="display:flex;gap:12px;align-items:center;margin:8px"><b style="width:80px;color:#eee">${n}</b><img src="${d(`qa/out/hover-${n}-a.png`)}"><img src="${d(`qa/out/hover-${n}-b.png`)}"></div>`).join("");
const s = await b.newPage({ viewport: { width: 1300, height: 600 } });
await s.setContent(`<body style="margin:0;background:#111;font:12px sans-serif">${rows}</body>`); await s.screenshot({ path: "qa/out/hover-sheet.png", fullPage: true });
await b.close(); console.log("ok");
