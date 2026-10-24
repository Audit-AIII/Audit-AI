// Contrast of muted text tokens vs the real background. Reads the computed colour of real
// caption elements and samples the rendered (grained) background around them.
// AUDIT_EMAIL / AUDIT_PASSWORD / REVIEW_ID env.
import { chromium } from "playwright";
const { AUDIT_EMAIL: email, AUDIT_PASSWORD: password, REVIEW_ID: rid } = process.env;
const lum = ([r, g, b]) => { const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const canvas = hex("#d4b08f");
console.log("Tokens vs --canvas #d4b08f:");
for (const [n, h] of [["--ink", "#36261a"], ["--ink-2", "#6b4c34"], ["--accent", "#8c5940"], ["--light-glow", "#7b5b41"], ["--surface", "#47331f"]]) console.log(`  ${n.padEnd(12)} ${h}  ${ratio(hex(h), canvas).toFixed(2)}:1`);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
await p.goto(`http://localhost:3000/login?next=${encodeURIComponent(`/app/review?id=${rid}`)}`, { waitUntil: "networkidle" });
await p.fill("#a-email", email); await p.fill("#a-password", password); await p.click("button[type=submit]");
await p.waitForURL("**/app/review**", { timeout: 20000 }); await p.waitForTimeout(1500);
const targets = [[".engine-note", "Checked by … line"], [".panel__hint", "panel hint"], [".add-muted", "add-muted caption"], [".t-caption", "caption"]];
for (const [path, sels] of [[`/app/review?id=${rid}`, [".engine-note"]], ["/app/sources", [".panel__hint"]], [`/app/review-edit?id=${rid}`, [".add-muted"]]]) {
  await p.goto("http://localhost:3000" + path, { waitUntil: "networkidle" }); await p.waitForTimeout(1200);
  for (const sel of sels) {
    const el = p.locator(sel).first(); if (!(await el.count())) { console.log(`  ${sel}: not on ${path}`); continue; }
    const color = await el.evaluate((e) => getComputedStyle(e).color);
    const fg = color.match(/\d+(\.\d+)?/g).slice(0, 3).map(Number);
    // background: hide the text, screenshot the box, average + darkest/lightest quartiles
    await el.evaluate((e) => (e.style.color = "transparent"));
    const buf = await el.screenshot(); await el.evaluate((e) => (e.style.color = ""));
    const bg = await p.evaluate(async (b64) => { const i = new Image(); i.src = "data:image/png;base64," + b64; await i.decode(); const c = new OffscreenCanvas(i.width, i.height); const x = c.getContext("2d"); x.drawImage(i, 0, 0);
      const d = x.getImageData(0, 0, i.width, i.height).data; const px = []; for (let k = 0; k < d.length; k += 4) px.push([d[k], d[k + 1], d[k + 2]]);
      px.sort((a, b) => a[0] + a[1] + a[2] - (b[0] + b[1] + b[2])); const avg = (arr) => [0, 1, 2].map((j) => arr.reduce((s, q) => s + q[j], 0) / arr.length);
      return { mean: avg(px), light: avg(px.slice(Math.floor(px.length * 0.75))) }; }, buf.toString("base64"));
    console.log(`  ${sel.padEnd(14)} on ${path.split("?")[0].padEnd(16)} text ${color}  vs bg mean ${ratio(fg, bg.mean).toFixed(2)}:1, vs light grain ${ratio(fg, bg.light).toFixed(2)}:1`);
  }
}
await b.close();
