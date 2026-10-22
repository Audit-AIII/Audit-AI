import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("https://relevovinco.com", { waitUntil: "networkidle" }); await p.waitForTimeout(800);
const r = await p.evaluate(() => {
  const out = {};
  const props = ["content","color","background-image","background-clip","-webkit-background-clip","-webkit-text-fill-color","-webkit-text-stroke","text-shadow","filter","position","inset","mix-blend-mode","opacity","transform","display","z-index","font-size"];
  for (const s of [".hero__line--cut .hero__word", ".hero__line--raised .hero__word", ".hero__channel"]) {
    const e = document.querySelector(s);
    for (const ps of [null, "::before", "::after"]) { const c = getComputedStyle(e, ps); const o = {}; for (const k of props) { const v = c.getPropertyValue(k); if (v && !["none","normal","auto",""].includes(v)) o[k] = v.slice(0, 200); } out[s + (ps || "")] = o; }
    out[s + " html"] = e.outerHTML.slice(0, 400);
  }
  const rules = []; for (const sh of document.styleSheets) { let l; try { l = sh.cssRules } catch { continue } const w = (rs) => { for (const r of rs) { if (r.cssRules) w(r.cssRules); if (r.selectorText && /m-cut|m-raised|m-ply|m-board|m-surface|m-title|m-text|reveal|\[data-|faq__|m-icon|nav__toggle|craft__/.test(r.selectorText)) rules.push(r.cssText.replace(/url\("data[^)]*\)/g, "url(GRAIN)").slice(0, 420)); } }; w(l); }
  out.rules = rules; return out; });
console.log(JSON.stringify(r, null, 1));
await b.close();
