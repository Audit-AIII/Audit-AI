// node --experimental-strip-types qa/unit/evaluation-run.test.mts
// Fixture: the GET /api/evaluations/latest example in services/api/API.md (EvaluationOut).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { formatRate, looksLikeRunEvaluation, measured, providerModeText, ratioText, runEvaluationProblem } from "../../lib/additions/evaluationRun.ts";

const fx = JSON.parse(readFileSync(new URL("../fixtures/evaluation-run.api-example.json", import.meta.url), "utf8"));

// valid response parses
assert.equal(runEvaluationProblem(fx), null);
assert.equal(looksLikeRunEvaluation(fx), true);
assert.equal(looksLikeRunEvaluation({ contract: "evaluation-summary-v1", state: "none" }), false, "old shape goes to the old parser");

// missing per_check is rejected
const { per_check: _drop, ...noChecks } = fx;
void _drop;
assert.match(runEvaluationProblem(noChecks) ?? "", /per_check/);
// wrong types rejected, never defaulted
assert.match(runEvaluationProblem({ ...fx, catch_rate: "1.0" }) ?? "", /catch_rate/);
assert.match(runEvaluationProblem({ ...fx, by_split: { dev: { n: 1 } } }) ?? "", /by_split\.dev/);
assert.equal(runEvaluationProblem({ ...fx, by_split: null }), null, "older runs: by_split null is fine");

// null rates render as "–", not 0
assert.equal(formatRate(null), "–");
assert.equal(formatRate(fx.per_check[2].false_positive_rate), "–");
assert.equal(formatRate(0), "0%");
assert.equal(formatRate(1), "100%");
assert.equal(formatRate(0.0364), "3.64%", "backend precision kept");

// Missing vs zero: a real 0 is a result; nothing measured is not.
assert.equal(measured(0), "0%");
assert.equal(measured(1), "100%");
assert.equal(measured(null), null);
assert.equal(measured(0.5, 0), null, "a check that covered no claims");
assert.equal(measured(0, 26), "0%");
assert.equal(ratioText({ numerator: 37, denominator: 40, value: 0.925 }), "37 of 40 (92.5%)");
assert.equal(ratioText({ numerator: 0, denominator: 18, value: 0 }), "0 of 18 (0%)");
assert.equal(ratioText({ numerator: 0, denominator: 0, value: null }), null);

// An optional headline is checked when present, and its absence is fine.
const headRatio = { numerator: 1, denominator: 2, value: 0.5 };
assert.equal(runEvaluationProblem({ ...fx }), null);
assert.equal(runEvaluationProblem({ ...fx, headline: { split: "heldout", n: 2, catch_rate: headRatio, false_positive_rate: headRatio } }), null);
assert.match(String(runEvaluationProblem({ ...fx, headline: { split: "heldout", n: 2, catch_rate: 0.5, false_positive_rate: headRatio } })), /headline/);

// provider mode is words
assert.equal(providerModeText("scripted").label, "Offline test run, not a real model.");
assert.equal(providerModeText("live").live, true);
console.log("evaluation run: all assertions passed");
