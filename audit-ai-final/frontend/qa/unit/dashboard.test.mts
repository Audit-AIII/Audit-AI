// node --experimental-strip-types qa/unit/dashboard.test.mts
// Fixtures shaped like the API.md Review example (status, created_at, findings with category /
// check_type / verification_status); counts are only what the reviews contain.
import assert from "node:assert/strict";
import { lastDays, placeholderCount, statusCounts, verdictMix } from "../../lib/additions/dashboard.ts";

const f = (verification_status: string, extra: Record<string, unknown> = {}) => ({ category: null, check_type: "retrieval", verification_status, ...extra });
const now = new Date(2026, 9, 25, 15, 0, 0); // 25 Oct 2026, local
const day = (n: number) => new Date(2026, 9, 25 - n, 10, 0, 0).toISOString();
const reviews = [
  { status: "needs_human_review", created_at: day(0), findings: [f("contradicted"), f("unverified"), f("not_applicable", { check_type: "rule", category: "terminology" })] },
  { status: "needs_human_review", created_at: day(0), findings: [f("unverified"), f("conflicting_sources")] },
  { status: "approved", created_at: day(2), findings: [f("supported"), f("supported")] },
  { status: "rejected", created_at: day(3), findings: [f("contradicted")] },
  { status: "failed", created_at: day(9), findings: [] },
  { status: "needs_human_review", created_at: day(1), findings: [f("unverified", { category: "stub" })] },
] as never[];

const s = Object.fromEntries(statusCounts(reviews).map((g) => [g.key, g.count]));
assert.deepEqual(s, { waiting: 3, clean: 0, approved: 1, sent_back: 1, recheck: 0, failed: 1, running: 0 });
assert.equal(statusCounts([]).length, 7, "fixed rows, zeros kept");

assert.deepEqual(verdictMix(reviews), { contradicted: 2, conflicting_sources: 1, unverified: 2, rule: 1, supported: 2 }, "placeholder finding left out");
assert.equal(placeholderCount(reviews), 1);

const d = lastDays(reviews, 7, now);
assert.equal(d.length, 7);
assert.equal(d[6].label, "Today");
assert.deepEqual(d.map((x) => x.count), [0, 0, 0, 1, 1, 1, 2], "9 days ago is outside the window");
console.log("dashboard: all assertions passed");
