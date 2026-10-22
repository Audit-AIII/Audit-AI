// Zoomed side-by-side crops: node qa/crop.mjs <ref> <ours> <name> x,y,w,h [zoom=2]
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { extname } from "node:path";
const [ref, ours, name, box, zoomArg] = process.argv.slice(2);
const [x, y, w, h] = box.split(",").map(Number); const z = Number(zoomArg ?? 2);
const d = (p) => `data:image/${extname(p).slice(1).replace("jpg", "jpeg")};base64,${readFileSync(p).toString("base64")}`;
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: Math.ceil(w * z * 2 + 16), height: Math.ceil(h * z) } });
const pane = (src) => `<div style="width:${w * z}px;height:${h * z}px;overflow:hidden;position:relative"><img src="${src}" style="position:absolute;left:${-x * z}px;top:${-y * z}px;width:1182px;transform:scale(${z});transform-origin:0 0;image-rendering:pixelated"></div>`;
await p.setContent(`<body style="margin:0;display:flex;gap:16px;background:#111">${pane(d(ref))}${pane(d(ours))}</body>`);
await p.screenshot({ path: `qa/out/crop-${name}.png` }); await b.close(); console.log(`qa/out/crop-${name}.png`);
