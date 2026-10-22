// node qa/stitch.mjs out.png a.png b.png ... → images side by side
import { chromium } from "playwright"; import { readFileSync } from "node:fs";
const [out, ...files] = process.argv.slice(2);
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 400 * files.length, height: 860 } });
await p.setContent(`<body style="margin:0;display:flex;gap:10px;background:#111">${files.map((f) => `<img src="data:image/png;base64,${readFileSync(f).toString("base64")}" style="width:390px">`).join("")}</body>`);
await p.screenshot({ path: out }); await b.close();
