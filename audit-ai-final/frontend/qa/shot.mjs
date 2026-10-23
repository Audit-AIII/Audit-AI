// Visual QA: screenshots of the local page and side-by-side comparisons with a reference image.
// Usage:
//   node qa/shot.mjs <name> [--y=<scrollY>|--sel=<css selector>] [--ref=<reference image path>] [--w=1182 --h=937] [--wait=1600] [--full]
// Output: qa/out/<name>.png and, with --ref, qa/out/<name>-compare.png (reference left, ours right).
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { resolve, extname } from "node:path";

const args = Object.fromEntries(
  process.argv.slice(3).map((a) => {
    const [k, v] = a.replace(/^--/, "").split("=");
    return [k, v ?? true];
  }),
);
const name = process.argv[2] ?? "shot";
const w = Number(args.w ?? 1182);
const h = Number(args.h ?? 937);
const url = args.url ?? "http://localhost:3000/";
const out = `qa/out/${name}.png`;

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
await page.goto(url, { waitUntil: "networkidle" });
await page.evaluate(() => document.fonts.ready);
if (args.sel) {
  await page.evaluate((s) => document.querySelector(s)?.scrollIntoView({ block: "start" }), args.sel);
} else if (args.y) {
  await page.evaluate((y) => window.scrollTo(0, y), Number(args.y));
}
await page.waitForTimeout(Number(args.wait ?? 1600));
await page.screenshot({ path: out, fullPage: Boolean(args.full) });

if (args.ref) {
  const toData = (p) => `data:image/${extname(p).slice(1).replace("jpg", "jpeg")};base64,${readFileSync(resolve(p)).toString("base64")}`;
  const cmp = await browser.newPage({ viewport: { width: w * 2 + 24, height: h + 40 } });
  await cmp.setContent(`<body style="margin:0;background:#111;color:#eee;font:13px sans-serif;display:flex;gap:24px">
    <figure style="margin:0"><figcaption style="height:40px;line-height:40px">reference</figcaption><img src="${toData(args.ref)}" style="width:${w}px;display:block"></figure>
    <figure style="margin:0"><figcaption style="height:40px;line-height:40px">ours</figcaption><img src="${toData(out)}" style="width:${w}px;display:block"></figure></body>`);
  await cmp.screenshot({ path: `qa/out/${name}-compare.png`, fullPage: true });
}
await browser.close();
console.log("wrote", out, args.ref ? `and qa/out/${name}-compare.png` : "");
