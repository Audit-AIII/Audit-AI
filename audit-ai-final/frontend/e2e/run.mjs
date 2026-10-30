// Runs every journey in order against the real backend and prints pass, fail and skip counts.
// Usage: AUDIT_PASSWORD=<seed.py DEMO_PASSWORD> node e2e/run.mjs [journey-number ...]
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { apiAs, signInApi } from "./lib.mjs";

export class Skip extends Error {}

const JOURNEYS = [
  "01-upload-to-findings",
  "02-correction",
  "03-solo-decision",
  "04-team-workflow",
  "05-refusals",
  "06-audit",
  "07-team-management",
  "08-workspace-switch",
  "09-dismiss-comment-lock",
  "10-scorecard",
  "11-errors",
  "12-responsive",
  "13-tone",
];
const only = process.argv.slice(2);
const OUT = "qa/out/e2e";
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const shared = { asha: await signInApi("asha@seed.inkloom.demo") };

// These journeys must not depend on, or spend, a live AI provider.
const probe = await apiAs(shared.asha)("/api/evaluations", { method: "POST" });
if (probe.status !== 409) {
  await browser.close();
  throw new Error(`This server may have an AI provider set up (POST /api/evaluations answered ${probe.status}). Start it with no keys. See e2e/README.md.`);
}

const results = [];
for (const name of JOURNEYS) {
  if (only.length && !only.includes(name.slice(0, 2))) continue;
  const run = { browser, shared, open: [], pageErrors: [] };
  const started = Date.now();
  try {
    const { default: journey } = await import(`./${name}.mjs`);
    await journey(run);
    if (run.pageErrors.length) throw new Error(`Uncaught page errors: ${run.pageErrors.join(" | ")}`);
    results.push([name, "pass", ""]);
    console.log(`pass  ${name} (${Math.round((Date.now() - started) / 1000)}s)`);
  } catch (err) {
    if (err?.name === "Skip" || err instanceof Skip) {
      results.push([name, "skip", err.message]);
      console.log(`skip  ${name}: ${err.message}`);
    } else {
      results.push([name, "fail", err.message]);
      console.log(`FAIL  ${name}\n      ${String(err.message).split("\n").slice(0, 8).join("\n      ")}`);
      for (const [i, p] of run.open.entries()) await p.screenshot({ path: `${OUT}/${name}-${i}.png`, fullPage: true }).catch(() => {});
    }
  }
  for (const p of run.open) await p.context().close().catch(() => {});
}
await browser.close();
const count = (s) => results.filter((r) => r[1] === s).length;
console.log(`\n${count("pass")} passed, ${count("fail")} failed, ${count("skip")} skipped`);
process.exit(count("fail") ? 1 : 0);
