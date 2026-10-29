// Before/after screenshots for the performance work, with every animation frozen at a fixed time so
// two runs can be diffed pixel by pixel.
//   node qa/perf-shots.mjs before        (writes qa/out/perf-shots/before/*.png)
//   node qa/perf-shots.mjs after
//   node qa/perf-shots.mjs diff          (compares before/ and after/)
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { chromium } from "playwright";

const WEB = process.env.WEB ?? "http://localhost:3000";
const mode = process.argv[2] ?? "before";
const OUT = new URL("./out/perf-shots/", import.meta.url);
const SESSION = JSON.stringify({ email: "perf@example.test", token: "perf-token", userId: "u1", organisation: { id: "o1", name: "Perf", slug: "perf" }, role: "admin" });
const VIEWPORTS = { desktop: { width: 1182, height: 937 }, mobile: { width: 390, height: 844 } };
// Landing page at several scroll depths (fractions of the scrollable height), plus the other routes.
const SHOTS = [
  ...[0, 0.12, 0.25, 0.4, 0.55, 0.7, 0.85, 1].map((f) => ({ path: "/", scroll: f, name: `home-${Math.round(f * 100)}` })),
  { path: "/login", name: "login" },
  { path: "/app/sources", name: "app-sources" },
  { path: "/app/review", name: "app-review" },
];

/** Finish one-shot animations and park infinite ones at the same moment, so frames are repeatable. */
const freeze = () =>
  document.getAnimations().forEach((a) => {
    const t = a.effect?.getTiming?.();
    if (t && t.iterations === Infinity) {
      a.pause();
      a.currentTime = 4000;
    } else a.finish?.();
  });

async function capture(dir) {
  mkdirSync(new URL(`${dir}/`, OUT), { recursive: true });
  const b = await chromium.launch();
  for (const [vp, viewport] of Object.entries(VIEWPORTS)) {
    for (const s of SHOTS) {
      const ctx = await b.newContext({ viewport });
      if (s.path.startsWith("/app")) await ctx.addInitScript((x) => localStorage.setItem("audit-ai.session", x), SESSION);
      const p = await ctx.newPage();
      await p.goto(WEB + s.path, { waitUntil: "load" });
      await p.evaluate(() => document.fonts.ready);
      await p.waitForTimeout(2500);
      if (s.scroll !== undefined && s.scroll > 0) {
        // Jump straight to an exact position (wheel + Lenis easing lands somewhere slightly different
        // each run), then let the scrubs and the process step tween (1.8s) settle.
        await p.evaluate((f) => window.scrollTo(0, Math.round((document.documentElement.scrollHeight - innerHeight) * f)), s.scroll);
        await p.waitForTimeout(3500);
      }
      await p.evaluate(freeze);
      await p.waitForTimeout(400);
      await p.screenshot({ path: new URL(`${dir}/${vp}-${s.name}.png`, OUT).pathname.replace(/^\/([A-Z]:)/, "$1") });
      await ctx.close();
    }
  }
  await b.close();
  console.log(`saved ${dir}`);
}

async function diff() {
  const b = await chromium.launch();
  const p = await b.newPage();
  const rows = [];
  for (const f of readdirSync(new URL("before/", OUT)).filter((n) => n.endsWith(".png"))) {
    const a = readFileSync(new URL(`before/${f}`, OUT)).toString("base64");
    let c;
    try {
      c = readFileSync(new URL(`after/${f}`, OUT)).toString("base64");
    } catch {
      rows.push({ shot: f, error: "missing after" });
      continue;
    }
    const r = await p.evaluate(async ({ a, c }) => {
      const load = async (b64) => {
        const i = new Image();
        i.src = "data:image/png;base64," + b64;
        await i.decode();
        const cv = new OffscreenCanvas(i.width, i.height);
        const x = cv.getContext("2d");
        x.drawImage(i, 0, 0);
        return { d: x.getImageData(0, 0, i.width, i.height).data, w: i.width, h: i.height };
      };
      const A = await load(a), C = await load(c);
      if (A.w !== C.w || A.h !== C.h) return { sizeMismatch: `${A.w}x${A.h} vs ${C.w}x${C.h}` };
      let sum = 0, max = 0, px8 = 0;
      for (let k = 0; k < A.d.length; k += 4) {
        let m = 0;
        for (let ch = 0; ch < 3; ch++) {
          const d = Math.abs(A.d[k + ch] - C.d[k + ch]);
          sum += d;
          if (d > m) m = d;
        }
        if (m > max) max = m;
        if (m > 8) px8++;
      }
      const n = A.d.length / 4;
      return { meanAbs: +(sum / (n * 3)).toFixed(3), maxChannel: max, pctPixelsOver8: +((100 * px8) / n).toFixed(3) };
    }, { a, c });
    rows.push({ shot: f, ...r });
  }
  await b.close();
  console.table(rows);
  writeFileSync(new URL("diff.json", OUT), JSON.stringify(rows, null, 2));
}

if (mode === "diff") await diff();
else await capture(mode);
