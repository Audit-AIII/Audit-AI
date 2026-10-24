// node --experimental-strip-types qa/unit/evaluation-run.test.mts
// Fixture: the GET /api/evaluations/latest example in services/api/API.md (EvaluationOut).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { formatRate, looksLikeRunEvaluation, providerModeText, runEvaluationProblem } from "../../lib/additions/evaluationRun.ts";

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

// provider mode is words
assert.equal(providerModeText("scripted").label, "Offline test run, not a real model.");
assert.equal(providerModeText("live").live, true);
console.log("evaluation run: all assertions passed");
