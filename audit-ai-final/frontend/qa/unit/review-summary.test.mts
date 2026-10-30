// node --experimental-strip-types qa/unit/review-summary.test.mts
// Summary counts (docs/governance.md 9.4), review states and spans in code points.
import assert from "node:assert/strict";
import { isChecking, isPartialReview, relationLook, reviewReasonText, severity, validationLook, verdict } from "../../components/app/reviewLabels.ts";
import { countText, isStyleRule, toneCount } from "../../lib/additions/summary.ts";
import { spanLocated } from "../../lib/text/codepoints.ts";

// Missing vs zero: a real 0 is 0, a missing count is never 0.
assert.equal(countText(0), "0");
assert.equal(countText(3), "3");
assert.equal(countText(undefined), "–");
assert.equal(countText(null), "–");
assert.equal(toneCount(null), 0, "no style line to show when counts are missing");

// Only the two style rules count, and only on rule findings.
assert.equal(isStyleRule({ check_type: "rule", rule_type: "all_caps_run" }), true);
assert.equal(isStyleRule({ check_type: "rule", rule_type: "emoji_run" }), true);
assert.equal(isStyleRule({ check_type: "rule", rule_type: "spelling" }), false);
assert.equal(isStyleRule({ check_type: "retrieval", rule_type: null }), false);

// Spans are code points: emoji and accents must not shift the match.
const text = "🎧🎧 Café Lumen lasts 24 hours.";
assert.equal(spanLocated(text, { start: 3, end: 14 }, "Café Lumen "), true, "emoji before the span");
assert.equal(spanLocated(text, { start: 8, end: 13 }, "Lumen"), true, "after an accent");
assert.equal(spanLocated(text, { start: 0, end: 5 }, "Lumen"), false, "mismatched span");
assert.equal(spanLocated("The Pods\nlast long.", { start: 4, end: 18 }, "Pods last long"), true, "reflowed whitespace is the same words");
assert.equal(spanLocated("Short.", { start: 40, end: 50 }, "Lumen"), false, "span past the end");

// Unknown values never crash and stay readable. Unverified is never worded as false.
assert.equal(verdict("unverified").label, "Not proven yet");
assert.equal(verdict("brand_new_verdict").label, "Brand new verdict");
assert.deepEqual(severity("extreme"), { marks: "○○○○", word: "Extreme" });
assert.equal(reviewReasonText("not_enough_evidence"), "No approved document covers this");
assert.equal(reviewReasonText("unsupported_component"), "Unsupported component");
assert.equal(relationLook("contradicts").label, "Disagrees");
assert.equal(relationLook("mentions").label, "Mentions");
assert.equal(validationLook("validated").label, "Quote verified");
assert.equal(validationLook("span_not_found").label, "Quote could not be verified");

// Review states.
const review = (over: object) => ({ status: "completed", report_status: null, rules_status: "complete", error_summary: null, findings: [], ...over }) as never;
assert.equal(isPartialReview(review({})), false, "a clean review is not partial");
assert.equal(isPartialReview(review({ rules_status: "incomplete" })), true);
assert.equal(isPartialReview(review({ report_status: "PARTIAL" })), true, "the engine's own value");
assert.equal(isPartialReview(review({ report_status: "COMPLETED" })), false);
assert.equal(isPartialReview(review({ error_summary: "one claim failed", findings: [{}] })), true);
assert.equal(isPartialReview(review({ error_summary: "failed", findings: [{}], rules_status: "not_applied" })), false, "not_applied has its own message");
assert.equal(isPartialReview(review({ status: "failed", rules_status: "incomplete" })), false, "failed is not partial");
for (const status of ["draft", "queued", "analysing"]) assert.equal(isChecking(review({ status })), true, status);
for (const status of ["completed", "failed", "needs_human_review"]) assert.equal(isChecking(review({ status })), false, status);

console.log("review summary: all assertions passed");
