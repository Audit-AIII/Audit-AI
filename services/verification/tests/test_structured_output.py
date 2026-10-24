"""PROMPTS.md Phase 5: structured-output validation for the extractor, verifier and corrector.

Model replies are never trusted to be JSON because the prompt asked for JSON. They are parsed
strictly, validated against closed Pydantic models, repaired a bounded number of times, and then
reported as MALFORMED_MODEL_OUTPUT (HTTP 422 UNPARSEABLE_MODEL_OUTPUT when no claim could be
checked). Mocked providers only."""

import logging
import warnings
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

warnings.filterwarnings("ignore", message=".*httpx.*", category=DeprecationWarning)
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from e2e_support import CONTENT, DOCS, ERROR_CLAIM, RoutedProvider, careful_model, request  # noqa: E402
from inkloom_verify.api import create_verify_router, install_dev_error_handlers  # noqa: E402
from inkloom_verify.api_contract import VerdictResult  # noqa: E402
from inkloom_verify.correction import ClaimCorrector, CorrectionConfig  # noqa: E402
from inkloom_verify.evaluation.corrections import contradicted_result, load_cases  # noqa: E402
from inkloom_verify.extraction import ClaimExtractor, ExtractionConfig  # noqa: E402
from inkloom_verify.pipeline import PipelineEngine, verify_request  # noqa: E402
from inkloom_verify.providers.base import (
    JsonCompletionRequest,
    MalformedOutputError,
    ProviderTimeoutError,
    parse_json_object,
)  # noqa: E402
from inkloom_verify.providers.openrouter import OpenRouterProvider, OpenRouterSettings  # noqa: E402
from inkloom_verify.retrieval import BM25Retriever  # noqa: E402
from inkloom_verify.schemas import CorrectionStatus, ErrorCode, GuardRejectionReason, Verdict  # noqa: E402
from inkloom_verify.verification import ClaimVerifier, VerificationConfig, verify_claim  # noqa: E402


CASES = {
    c.case_id: c
    for c in load_cases(
        Path(__file__).resolve().parents[1] / "eval" / "data" / "corrections_v1.jsonl"
    )
}
SECRET = "sk-or-v1-0000SECRETSECRET0000"


# --- 1. Strict JSON parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ('{"verdict": "SUPPORTED"', "truncated"),
        ('{"verdict": "SUPPORTED", "citations": [{"passage": "P1", "quo', "truncated mid-string"),
        ("{not json}", "malformed"),
        ("", "empty"),
        ('Sure! Here is the JSON: {"verdict": "SUPPORTED"}', "prose around JSON"),
        (
            '{"verdict": "NOT_ENOUGH_EVIDENCE", "verdict": "SUPPORTED"}',
            "duplicate key: Python's json keeps the last",
        ),
        ('{"citations": [], "score": NaN}', "NaN is not JSON"),
        ('{"score": Infinity}', "Infinity is not JSON"),
        ('[{"verdict": "SUPPORTED"}]', "an array, not an object"),
        ('"SUPPORTED"', "a string, not an object"),
        ('```json\n{"verdict": "SUPPORTED"}\n``` trailing', "text after the fence"),
        ("[" * 100_000 + "]" * 100_000, "pathologically nested"),
    ],
    ids=lambda v: v[:40]
    if len(v) < 200
    else "deeply-nested",  # short ids: Windows limits environment variables
)
def test_strict_parsing_refuses(text, why):
    with pytest.raises(MalformedOutputError) as refused:
        parse_json_object(text)
    assert "SUPPORTED" not in str(refused.value) and len(str(refused.value)) < 60, (
        why
    )  # never echoes the reply


def test_strict_parsing_accepts_a_plain_object_and_one_code_fence():
    assert parse_json_object('{"verdict": "SUPPORTED"}') == {"verdict": "SUPPORTED"}
    assert parse_json_object('```json\n{"verdict": "SUPPORTED"}\n```') == {"verdict": "SUPPORTED"}


def test_a_duplicate_key_nested_anywhere_is_refused():
    with pytest.raises(MalformedOutputError):
        parse_json_object('{"citations": [{"passage": "P1", "passage": "P2", "quote": "x"}]}')


# --- 2. The adapter uses it, and retries are bounded --------------------------------------------------


def openrouter(content: str, finish: str = "stop", models=("google/gemini-flash",), max_retries=2):
    calls = []

    def transport(req):
        calls.append(req)
        return httpx.Response(
            200,
            json={
                "model": "google/gemini-flash",
                "choices": [{"finish_reason": finish, "message": {"content": content}}],
            },
        )

    adapter = OpenRouterProvider(
        OpenRouterSettings(
            api_key="sk-or-v1-TEST-ONLY-NOT-A-REAL-KEY-000000",
            models=list(models),
            max_retries=max_retries,
        ),
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=lambda s: None,
    )
    return adapter, calls


REQ = JsonCompletionRequest(
    system="s", user="u", schema_name="claim_verification", json_schema={"type": "object"}
)


@pytest.mark.parametrize(
    ("content", "finish"),
    [
        ('{"verdict": "NOT_ENOUGH_EVIDENCE", "verdict": "SUPPORTED"}', "stop"),
        ('{"verdict": "SUPP', "stop"),
        ('{"verdict": "SUPPORTED"}', "length"),
    ],
    ids=["duplicate-key", "truncated", "cut-off-by-token-limit"],
)
def test_the_adapter_never_passes_on_invalid_json(content, finish):
    adapter, _ = openrouter(content, finish)
    with pytest.raises(MalformedOutputError):
        adapter.complete_json(REQ)


@pytest.mark.parametrize(
    ("models", "max_retries", "calls"),
    [
        (("google/gemini-flash",), 0, 1),
        (("google/gemini-flash",), 2, 3),
        (("google/gemini-flash", "meta-llama/llama"), 2, 6),
    ],
)
def test_adapter_retries_of_invalid_json_are_bounded(models, max_retries, calls):
    adapter, seen = openrouter("{not json", models=models, max_retries=max_retries)
    with pytest.raises(MalformedOutputError):
        adapter.complete_json(REQ)
    assert len(seen) == calls  # models x (1 + max_retries), never more


# --- 3. Each component validates, repairs a bounded number of times, then gives up ---------------


def extractor_with(reply, **config):
    provider = RoutedProvider(lambda call: reply)
    return ClaimExtractor(provider, ExtractionConfig(**config)).extract(
        "Lumen Pods weigh 5 g."
    ), provider


@pytest.mark.parametrize(
    "reply",
    [
        {"statements": "none"},  # wrong type
        {"statements": [{"sentence_id": "s1", "kind": "factual"}]},  # missing required field
        {
            "statements": [{"sentence_id": "s1", "kind": "certain", "claims": []}]
        },  # invalid enum value
        {
            "statements": [
                {"sentence_id": "s1", "kind": "factual", "claims": [], "confidence": 0.9}
            ]
        },  # unexpected field
        {
            "statements": [{"sentence_id": 1, "kind": "factual", "claims": []}]
        },  # wrong type for an id
        {},
    ],  # nothing
    ids=["wrong-type", "missing-field", "invalid-enum", "extra-field", "id-as-number", "empty"],
)
def test_the_extractor_refuses_invalid_schema(reply):
    result, provider = extractor_with(reply)
    assert result.claims == [] and [e.code for e in result.errors] == [
        ErrorCode.MALFORMED_MODEL_OUTPUT
    ]
    assert len(provider.calls) == 2  # one call, one repair (the default)


def verifier_with(reply, **config):
    claim = {
        "claim_id": "clm_0001",
        "text": "Lumen Pods offer up to 12 hours of playback per charge.",
        "source_span": {"start": 0, "end": 55},
    }
    provider = RoutedProvider(reply if callable(reply) else (lambda call: reply))
    docs = [DOCS["pods-fact-sheet"]]
    return verify_claim(
        claim, BM25Retriever(docs), ClaimVerifier(provider, docs, VerificationConfig(**config))
    ), provider


@pytest.mark.parametrize(
    "reply",
    [
        {"verdict": "PROBABLY", "citations": [], "rationale": "x"},  # invalid verdict
        {
            "verdict": "supported",
            "citations": [],
            "rationale": "x",
        },  # wrong case is a different value
        {
            "verdict": "SUPPORTED",
            "citations": [{"passage": "P1"}],
            "rationale": "x",
        },  # missing quote
        {"verdict": "SUPPORTED", "citations": "P1", "rationale": "x"},  # wrong type
        {
            "verdict": "SUPPORTED",
            "citations": [],
            "rationale": "x",
            "confidence": 1.7,
        },  # invalid confidence: no such field
        {
            "verdict": "SUPPORTED",
            "citations": [],
            "rationale": "x",
            "confidence": 0.9,
        },  # even a valid-looking one
        {"verdict": "SUPPORTED", "rationale": "x"},
    ],  # missing citations
    ids=[
        "invalid-verdict",
        "lowercase-verdict",
        "missing-quote",
        "citations-string",
        "confidence-1.7",
        "confidence-0.9",
        "missing-citations",
    ],
)
def test_the_verifier_refuses_invalid_schema(reply):
    result, provider = verifier_with(reply)
    assert (
        result.verdict is Verdict.ERROR
        and result.error.code is ErrorCode.MALFORMED_MODEL_OUTPUT
        and result.citations == []
    )
    assert len(provider.calls) == 2


def corrector_with(reply, **config):
    result, content = contradicted_result(
        CASES["corr-v1-027"]
    )  # "Lumen Pods cost €99." vs "Price: €129 ..."
    provider = RoutedProvider(lambda call: reply)
    corrected = ClaimCorrector(provider, None, CorrectionConfig(recheck=False, **config)).correct(
        result, content
    )
    return corrected, provider


@pytest.mark.parametrize(
    "reply",
    [
        {
            "status": "fixed",
            "original_text": "€99",
            "replacement_text": "€129",
            "citations": ["C1"],
            "reason": "x",
        },  # invalid enum
        {
            "status": "corrected",
            "original_text": "€99",
            "replacement_text": "€129",
            "reason": "x",
        },  # missing citations
        {
            "status": "corrected",
            "original_text": "€99",
            "replacement_text": 129,
            "citations": ["C1"],
            "reason": "x",
        },  # wrong type
        {
            "status": "corrected",
            "original_text": "€99",
            "replacement_text": "€129",
            "citations": ["C1"],
            "reason": "x",
            "confidence": 1,
        },
    ],
    ids=["invalid-status", "missing-citations", "number-not-text", "extra-field"],
)
def test_the_corrector_refuses_invalid_schema_and_keeps_the_verdict(reply):
    corrected, provider = corrector_with(reply)
    assert corrected.verdict is Verdict.CONTRADICTED and corrected.correction is None
    assert corrected.correction_attempt.status is CorrectionStatus.FAILED
    assert corrected.correction_attempt.error.code is ErrorCode.MALFORMED_MODEL_OUTPUT
    assert len(provider.calls) == 2


@pytest.mark.parametrize("repairs", [0, 1, 2, 3])
def test_every_component_stops_at_its_configured_repair_limit(repairs):
    _, extraction_provider = extractor_with({"statements": "none"}, max_repairs=repairs)
    _, verification_provider = verifier_with({"verdict": "PROBABLY"}, max_repairs=repairs)
    _, correction_provider = corrector_with({"status": "fixed"}, max_repairs=repairs)
    assert (
        len(extraction_provider.calls)
        == len(verification_provider.calls)
        == len(correction_provider.calls)
        == 1 + repairs
    )


@pytest.mark.parametrize("config", [ExtractionConfig, VerificationConfig, CorrectionConfig])
def test_repair_limits_are_bounded(config):
    with pytest.raises(ValidationError):
        config(max_repairs=4)
    with pytest.raises(ValidationError):
        config(max_repairs=-1)


def test_repairs_list_problems_without_echoing_the_reply():
    _, provider = verifier_with(
        {"verdict": "PROBABLY_" + SECRET, "citations": [], "rationale": SECRET}
    )
    repair = provider.calls[1].user
    assert SECRET not in repair and "verdict" in repair


# --- 4. Valid JSON is still not evidence: the guard runs after validation -------------------------


@pytest.mark.parametrize(
    "reply",
    [
        {"verdict": "SUPPORTED", "citations": [], "rationale": "trust me"},
        {"verdict": "CONTRADICTED", "citations": [], "rationale": "trust me"},
    ],
    ids=["supported-no-evidence", "contradicted-no-evidence"],
)
def test_schema_valid_output_without_evidence_cannot_bypass_the_guard(reply):
    result, _ = verifier_with(reply)
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.citations == []
    assert [r.reason for r in result.citation_guard.rejected] == [GuardRejectionReason.NO_CITATION]


def test_schema_valid_output_with_an_invented_quote_cannot_bypass_the_guard():
    result, _ = verifier_with(
        {
            "verdict": "SUPPORTED",
            "citations": [{"passage": "P1", "quote": "up to 99 hours of playback"}],
            "rationale": "x",
        }
    )
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE


def test_schema_valid_but_unsafe_corrections_never_reach_the_report():
    corrected, _ = corrector_with(
        {
            "status": "corrected",
            "original_text": "€99",
            "replacement_text": "€0",
            "citations": ["C1"],
            "reason": "x",
        }
    )
    assert (
        corrected.correction is None
        and corrected.correction_attempt.status is CorrectionStatus.NEEDS_HUMAN_REVIEW
    )


def test_the_public_report_refuses_invalid_confidence():
    for bad in (1.7, -0.1, float("nan")):
        with pytest.raises(ValidationError):
            VerdictResult(
                status="SUPPORTED",
                confidence=bad,
                evidence=[{"doc_id": "d", "location": {"start": 0, "end": 1}, "quote": "x"}],
                needs_human_review=False,
            )


# --- 5. Model-output errors are not timeouts, at every level ---------------------------------------


def test_claim_level_codes_keep_timeouts_and_bad_output_apart():
    def mixed(call):
        if call.schema_name == "claim_verification" and "€99" in call.user:
            return {"verdict": "PROBABLY"}
        return careful_model(call)  # times out on ERROR_CLAIM

    report = verify_request(request(), RoutedProvider(mixed))
    codes = {r.claim.text: r.error.code for r in report.results if r.error}
    assert codes[ERROR_CLAIM] is ErrorCode.PROVIDER_TIMEOUT
    assert ErrorCode.MALFORMED_MODEL_OUTPUT in codes.values()


def endpoint(respond):
    app = FastAPI()
    install_dev_error_handlers(app)
    app.include_router(
        create_verify_router(
            PipelineEngine(RoutedProvider(respond)),
            reference_set_loader=lambda t, s: [DOCS["pods-fact-sheet"]],
            authenticated_tenant=lambda: "t",
        )
    )
    return TestClient(app).post(
        "/v1/verify",
        json={
            "request_id": "req_so",
            "content": {"id": "c1", "text": CONTENT},
            "reference_set_id": "r",
        },
    )


def test_when_nothing_could_be_checked_the_http_codes_differ_too():
    unparseable = endpoint(lambda call: {"statements": "none"})
    timeout = endpoint(lambda call: ProviderTimeoutError("slow"))
    assert (unparseable.status_code, unparseable.json()["error"]["code"]) == (
        422,
        "UNPARSEABLE_MODEL_OUTPUT",
    )
    assert (timeout.status_code, timeout.json()["error"]["code"]) == (504, "PROVIDER_TIMEOUT")


# --- 6. Nothing sensitive in logs -----------------------------------------------------------------


def test_invalid_output_is_not_logged(caplog):
    caplog.set_level(logging.DEBUG)
    leaky = {
        "statements": [
            {
                "sentence_id": "s1",
                "kind": SECRET,
                "claims": [{"text": SECRET, "source_quote": SECRET}],
            }
        ]
    }
    verify_request(request(), RoutedProvider(lambda call: leaky))
    assert SECRET not in caplog.text and "Lumen" not in caplog.text
