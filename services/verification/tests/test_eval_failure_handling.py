"""Provider failures during an evaluation are failures, never model decisions (2026-10-24).

A live run on a free model returned 78 ERROR records out of 80 and reported PASSED; the causes
were OpenRouter's data-policy refusal and its daily free-model quota. These tests drive the real
OpenRouter adapter and the real verifier over a fake HTTP transport (the network only; no model
answer is invented and nothing here measures model accuracy):

* quota exhaustion is a distinct, actionable PROVIDER_QUOTA_EXCEEDED error, never retried, and
  remembered so later records make no further calls;
* a data-policy refusal is remembered the same way; data_collection stays "deny";
* every failed record stays ERROR with its cause, and is never counted as a verdict class;
* partial failures above the 20% gate fail the run; below it they still show in the report.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from inkloom_verify.evaluation import required_metrics as rm
from inkloom_verify.evaluation.runner import (
    EngineVerifierPredictor,
    EvalPrediction,
    evaluate,
    load_records,
)
from inkloom_verify.providers.base import JsonCompletionRequest, ProviderQuotaError
from inkloom_verify.providers.openrouter import OpenRouterProvider, OpenRouterSettings
from inkloom_verify.schemas import ErrorCode, Verdict

ROOT = Path(__file__).resolve().parents[1]
RECORDS = load_records(ROOT / "eval" / "dataset.jsonl")
KEY = "sk-or-v1-TEST-ONLY-NOT-A-REAL-KEY-000000"
FREE = "nvidia/nemotron-3.5-super-vl:free"
PAID = "meta-llama/llama-3.3-70b-instruct"
REQUEST = JsonCompletionRequest(
    system="s", user="u", schema_name="claim_verification", json_schema={"type": "object"}
)

QUOTA_429 = {
    "error": {
        "code": 429,
        "message": "Rate limit exceeded: free-models-per-day. Add 10 credits to unlock 1000 free model requests per day",
    }
}
POLICY_404 = {
    "error": {
        "code": 404,
        "message": "No endpoints found matching your data policy (Free model training). Configure: https://openrouter.ai/settings/privacy",
    }
}

spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)


def adapter(handler, models=(FREE,)):
    calls: list[dict] = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        status, payload = handler(body)
        return httpx.Response(status, json=payload)

    sleeps: list[float] = []
    provider = OpenRouterProvider(
        OpenRouterSettings(api_key=KEY, models=list(models)),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=sleeps.append,
        jitter=lambda: 1.0,
    )
    return provider, calls, sleeps


def answer(data: dict, model: str) -> tuple[int, dict]:
    return 200, {
        "model": model,
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(data)}}],
    }


# --- Quota exhaustion -----------------------------------------------------------------------------


def test_quota_exhaustion_is_a_quota_error_with_an_actionable_message_and_no_retry():
    provider, calls, sleeps = adapter(lambda body: (429, QUOTA_429))
    with pytest.raises(ProviderQuotaError) as info:
        provider.complete_json(REQUEST)
    assert info.value.code is ErrorCode.PROVIDER_QUOTA_EXCEEDED and not info.value.retryable
    assert (
        len(calls) == 1 and sleeps == []
    )  # the provider said the quota is gone: no retry, no backoff
    assert "daily quota for :free models is exhausted" in str(info.value) and "paid model" in str(
        info.value
    )
    assert "Add 10 credits" not in str(info.value)  # the provider's own text is not echoed


def test_after_quota_exhaustion_free_models_are_skipped_without_calls_but_a_paid_model_is_tried():
    def handler(body):
        return (
            (429, QUOTA_429) if body["model"].endswith(":free") else answer({"x": 1}, body["model"])
        )

    provider, calls, _ = adapter(handler, models=(FREE, "liquid/lfm-2.5-2.6b:free", PAID))
    assert provider.complete_json(REQUEST).model == PAID
    assert [c["model"] for c in calls] == [
        FREE,
        PAID,
    ]  # the second :free model shares the quota: skipped
    assert provider.complete_json(REQUEST).model == PAID
    assert [c["model"] for c in calls] == [
        FREE,
        PAID,
        PAID,
    ]  # remembered: no new call to a :free model


def test_an_ordinary_429_is_still_a_retried_rate_limit():
    provider, calls, sleeps = adapter(
        lambda body: (429, {"error": {"code": 429, "message": "slow down"}})
    )
    with pytest.raises(Exception) as info:
        provider.complete_json(REQUEST)
    assert (
        info.value.code is ErrorCode.PROVIDER_RATE_LIMITED and len(calls) == 3 and len(sleeps) == 2
    )


# --- Data-policy incompatibility --------------------------------------------------------------


def test_a_data_policy_refusal_is_remembered_and_never_relaxes_data_collection():
    provider, calls, _ = adapter(lambda body: (404, POLICY_404))
    for _ in range(3):
        with pytest.raises(Exception):
            provider.complete_json(REQUEST)
    assert len(calls) == 1  # later records skip the refused model without a network call
    assert calls[0]["provider"] == {"data_collection": "deny", "require_parameters": True}


# --- Through the real verifier: failed records stay ERROR with their cause ---------------------


def test_a_quota_outage_gives_error_predictions_with_their_cause_and_one_network_call():
    provider, calls, _ = adapter(lambda body: (429, QUOTA_429))
    predictor = EngineVerifierPredictor(provider)
    sample = [r for r in RECORDS if r.split.value == "dev"][:6]
    predictions = {r.record_id: predictor.predict(r) for r in sample}
    assert all(p.verdict is Verdict.ERROR for p in predictions.values())
    assert {p.error_code for p in predictions.values()} == {"PROVIDER_QUOTA_EXCEEDED"}
    assert all("quota" in p.error_message for p in predictions.values())
    assert len(calls) <= 1  # the first record learns the quota is gone; the rest make no request

    metrics = rm.compute(sample, predictions)
    assert metrics.errors["by_code"] == {"PROVIDER_QUOTA_EXCEEDED": len(sample)}
    assert metrics.errors["counted_as_fn"] + metrics.errors["counted_as_tn"] == len(sample)
    assert metrics.provider_failure_rate.value == 1.0


def test_missing_and_failed_verdicts_are_never_counted_as_a_verdict_class():
    sample = RECORDS[:10]
    predictions = {
        r.record_id: EvalPrediction(
            record_id=r.record_id, verdict=Verdict.ERROR, error_code="PROVIDER_TIMEOUT"
        )
        for r in sample[:5]
    }  # the other 5 have no prediction at all
    results = evaluate(sample, predictions)
    confusion = results.verdict.confusion
    for gold in confusion:
        for predicted, n in confusion[gold].items():
            if n:
                assert (
                    predicted is Verdict.ERROR
                )  # nothing landed in SUPPORTED / CONTRADICTED / NOT_ENOUGH_EVIDENCE
    metrics = rm.compute(sample, predictions)
    assert metrics.errors["by_code"] == {"PROVIDER_TIMEOUT": 5, "MISSING_PREDICTION": 5}
    assert metrics.counts["error_predictions"] == 10 and metrics.counts["missing_predictions"] == 5


def test_error_fields_are_refused_on_a_real_verdict():
    with pytest.raises(ValueError, match="only allowed on an ERROR prediction"):
        EvalPrediction(record_id="x", verdict=Verdict.SUPPORTED, error_code="PROVIDER_TIMEOUT")


# --- Partial failures and the gate ----------------------------------------------------------------


def _predictions_file(tmp_path, failed: int) -> Path:
    lines = []
    for i, record in enumerate(RECORDS):
        p = {
            "record_id": record.record_id,
            "verdict": record.expected_verdict.value,
            "model_id": "replay/test",
            "citations": [
                {
                    "doc_id": g.doc_id,
                    "quote": g.quote,
                    "quote_span": {"start": g.span.start, "end": g.span.end},
                }
                for g in record.gold_evidence
            ],
        }
        if i < failed:
            p = {
                "record_id": record.record_id,
                "verdict": "ERROR",
                "citations": [],
                "error_code": "PROVIDER_QUOTA_EXCEEDED",
                "error_message": "OpenRouter's daily quota for :free models is exhausted",
            }
        lines.append(json.dumps(p))
    path = tmp_path / f"p{failed}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(("failed", "code"), [(78, 1), (24, 1), (8, 0)])
def test_partial_failures_fail_the_committed_baseline_above_20_percent_and_are_always_reported(
    tmp_path, failed, code
):
    """Uses the committed eval/baseline.json, so this is the gate CI and a live run actually apply."""
    out = tmp_path / "o"
    assert (
        run_eval.main(
            [
                "--predictions",
                str(_predictions_file(tmp_path, failed)),
                "--out",
                str(out),
                "--check-baseline",
            ]
        )
        == code
    )
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    errors = report["required_metrics"]["errors"]
    assert errors["by_code"] == {"PROVIDER_QUOTA_EXCEEDED": failed}
    [gate] = [g for g in report["gates"] if g["name"] == "model run: provider failure rate"]
    assert gate["status"] == ("FAIL" if code else "PASS")
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert (
        f"No verdict (ERROR): {failed} records" in markdown
        and "failures, not model decisions" in markdown
    )
