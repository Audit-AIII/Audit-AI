import { chromium } from "playwright";
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1182, height: 937 } });
await p.goto("https://relevovinco.com", { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
const r = await p.evaluate(() => {
  const props = ["box-shadow","background-color","background-image","transform","border-radius","inset","position","z-index","padding","margin","font-family","font-size","font-weight","line-height","letter-spacing","color","gap","display","grid-template-columns","width","height","opacity","clip-path","max-width"];
  const sels = ["#hero .hero__flap","#hero","#hero .hero__inner","#hero .hero__title","#hero .hero__aside","#hero .hero__aside p","#navigation","#navigation .nav__bar > a","#navigation nav","#navigation ul","main > section:nth-of-type(2)","main > section:nth-of-type(2) > *","#craft","[class*=craft]","[class*=craft__flap]"];
  const out = {};
  for (const s of sels) { const e = document.querySelector(s); if (!e) { out[s] = null; continue; }
    const cs = getComputedStyle(e), rc = e.getBoundingClientRect(); const o = { tag: e.tagName, cls: e.className?.toString(), rect: [rc.x,rc.y,rc.width,rc.height].map(Math.round) };
    for (const k of props) { const v = cs.getPropertyValue(k); if (v && v !== "none" && v !== "normal" && v !== "auto" && v !== "rgba(0, 0, 0, 0)" && !v.startsWith("url(\"data")) o[k] = v; }
    out[s] = o; }
  out.sections = [...document.querySelectorAll("body > * , main > *")].map(e => `${e.tagName}#${e.id}.${e.className}`.slice(0,80));
  return out; });
console.log(JSON.stringify(r, null, 1));
// scroll behaviour of the hero flap
await p.mouse.wheel(0, 400); await p.waitForTimeout(1200);
console.log(JSON.stringify(await p.evaluate(() => { const f = document.querySelector("#hero .hero__flap"), w = document.querySelector("#hero .hero__wash"), n = document.querySelector("#navigation");
  return { flap: getComputedStyle(f).transform, flapShadow: getComputedStyle(f).boxShadow, wash: getComputedStyle(w).opacity, navHidden: n.hasAttribute("data-hidden"), navAttrs: [...n.attributes].map(a=>a.name+"="+a.value), y: scrollY }; })));
await p.screenshot({ path: "qa/out/ref-scroll400.png" });
await b.close();
