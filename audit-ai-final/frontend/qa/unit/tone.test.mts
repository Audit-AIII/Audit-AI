// node --experimental-strip-types qa/unit/tone.test.mts
// Brand voice rule: a finding appears only with a validated guideline passage. Fixtures live only here.
import assert from "node:assert/strict";
import { hiddenToneText, isTone, isUncertainTone, splitTone, TONE_UNCERTAIN_MODE, withToneRule } from "../../lib/additions/tone.ts";

const tone = (over: object) =>
  ({ finding_id: "t", check_type: "tone", guideline_quote: "Never use exclamation marks in headlines.", validation_status: "validated", ...over }) as never;
const claim = { finding_id: "c", check_type: "retrieval" } as never;

assert.equal(TONE_UNCERTAIN_MODE, "omit", "the agreed default");
assert.equal(isTone(claim), false);

// With a validated passage: shown. Other findings are never touched.
assert.deepEqual(splitTone([claim, tone({})]).hidden, 0);
assert.equal(splitTone([claim, tone({})]).shown.length, 2);

// No passage: hidden in both modes, because a judgement with no source is never a finding.
for (const q of [null, undefined, "", "   "]) {
  assert.equal(splitTone([tone({ guideline_quote: q })]).hidden, 1, String(q));
  assert.equal(splitTone([tone({ guideline_quote: q })], "uncertain").hidden, 1, String(q));
}

// A passage that failed the server's check follows the mode.
for (const v of ["span_not_found", "unsupported", "downgraded", null, undefined, "new_value"]) {
  const f = tone({ validation_status: v });
  assert.equal(splitTone([f], "omit").hidden, 1, String(v));
  assert.equal(splitTone([f], "uncertain").hidden, 0, String(v));
  assert.equal(isUncertainTone(f), true, String(v));
}
assert.equal(isUncertainTone(tone({})), false);
assert.equal(isUncertainTone(claim), false);

// withToneRule returns the same review when nothing is hidden, and never adds a finding.
const review = (findings: unknown[]) => ({ id: "r", findings }) as never;
const clean = review([claim]);
assert.equal(withToneRule(clean), clean);
const out = withToneRule(review([claim, tone({ guideline_quote: "" }), tone({ validation_status: "unsupported" })]));
assert.equal(out.findings.length, 1);
assert.equal(out.hidden_tone_count, 2);

assert.equal(hiddenToneText(1), "1 brand voice observation hidden because it cites no valid guideline passage.");
assert.equal(hiddenToneText(2), "2 brand voice observations hidden because they cite no valid guideline passage.");

console.log("tone: all assertions passed");
