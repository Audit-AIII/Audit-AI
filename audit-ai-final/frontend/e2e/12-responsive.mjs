// Every core page on a phone: no sideways scroll, with real data.
import assert from "node:assert/strict";
import { go, noSidewaysScroll, pageAs, reviewsOf } from "./lib.mjs";

export default async function journey(run) {
  const { asha } = run.shared;
  const id = (await reviewsOf(asha)).find((r) => r.status === "needs_human_review").id;
  const p = await pageAs(run, asha, { width: 390, height: 844 });
  for (const path of [`/app/review?id=${id}`, `/app/decide?id=${id}`, "/app/queue", `/app/record?id=${id}`, "/app/scorecard", "/app/team", "/app/audit"]) {
    await go(p, path);
    assert.equal(await noSidewaysScroll(p), true, path);
  }
  const out = await pageAs(run, null, { width: 390, height: 844 });
  await go(out, "/invite/accept?token=abc");
  assert.equal(await noSidewaysScroll(out), true, "/invite/accept");
}
