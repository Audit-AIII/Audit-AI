// Which elements repaint? Traces `/` while idle and while scrolling, counts Paint events per DOM
// node and names each node by tag + class. Run against `npm start`.
//   node qa/perf-paint.mjs [mobile|desktop]
import { chromium } from "playwright";

const WEB = process.env.WEB ?? "http://localhost:3000";
const mobile = process.argv[2] === "mobile";
const b = await chromium.launch();
const ctx = await b.newContext(mobile ? { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true } : { viewport: { width: 1350, height: 940 } });
const p = await ctx.newPage();
const cdp = await ctx.newCDPSession(p);
await p.goto(WEB + "/", { waitUntil: "load" });
await p.waitForTimeout(3000);
await cdp.send("DOM.getDocument", { depth: -1 });

async function name(backendNodeId) {
  try {
    const { nodeIds } = await cdp.send("DOM.pushNodesByBackendIdsToFrontend", { backendNodeIds: [backendNodeId] });
    const { node } = await cdp.send("DOM.describeNode", { nodeId: nodeIds[0] });
    const attrs = node.attributes ?? [];
    const cls = attrs[attrs.indexOf("class") + 1];
    return `${node.localName || node.nodeName}${attrs.includes("class") && cls ? "." + cls.trim().split(/\s+/).join(".") : ""}`;
  } catch {
    return `#${backendNodeId}`;
  }
}

async function traced(what, fn) {
  await b.startTracing(p, { categories: ["devtools.timeline", "disabled-by-default-devtools.timeline"] });
  await fn();
  const events = JSON.parse((await b.stopTracing()).toString()).traceEvents;
  const per = new Map();
  for (const e of events) {
    if (e.name !== "Paint" || e.ph !== "X") continue;
    const id = e.args?.data?.nodeId;
    const cur = per.get(id) ?? { n: 0, ms: 0 };
    cur.n++;
    cur.ms += (e.dur ?? 0) / 1000;
    per.set(id, cur);
  }
  const rows = [...per.entries()].sort((a, b) => b[1].ms - a[1].ms).slice(0, 15);
  console.log(`\n== ${what} (${mobile ? "mobile" : "desktop"}): Paint events by node`);
  for (const [id, { n, ms }] of rows) console.log(`${String(n).padStart(6)} paints ${ms.toFixed(0).padStart(6)} ms  ${id ? await name(id) : "(no node)"}`);
}

await traced("idle 3s", () => p.waitForTimeout(3000));
await p.mouse.move(400, 400);
await traced("scroll", async () => {
  for (let i = 0; i < 60; i++) { await p.mouse.wheel(0, 240); await p.waitForTimeout(50); }
  await p.waitForTimeout(800);
});
await b.close();
