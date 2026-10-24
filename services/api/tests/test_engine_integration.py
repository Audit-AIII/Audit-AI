"""Step 6: the verification engine (Member 2) and this backend (Member 3), end to end.

Real routes, real auth, real Postgres, the real engine (extraction, retrieval, verification,
citation guard, corrections, softening) and this backend's own evidence re-validation. Only the
external model is replaced, by the backend's offline scripted provider or a scripted responder.

Covered: a successful review with all three verdicts and full provenance; corrections traceable to
the cited evidence; uncertain claims routed to a person; invalid, malformed and missing model
output; missing evidence; provider failures never turned into verdicts; partial failures.

Three contract gaps are pinned as strict expected failures (owner: backend). Each test turns red
as soon as the gap is fixed, so the contract cannot change silently:
  1. ClaimResult.conflicting_sources is not mapped to verification_status "conflicting_sources";
  2. the engine's safer wording (not evidence-backed) is stored in suggested_correction;
  3. deterministic rule findings (rules.evaluate_rules) are not run in reviews.
"""

from __future__ import annotations

import json
import uuid

import pytest
from inkloom_verify.providers.base import MalformedOutputError, ProviderRateLimitError, ProviderTimeoutError
from inkloom_verify.providers.fake import ResponderProvider

from conftest import DEFAULT_FACT_SHEET, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import ExternalCallLog

SUPPORTED = "Lumen Pods offer up to 12 hours of playback per charge."
CONTRADICTED = "Lumen Pods come with a 5 year warranty."
UNVERIFIED = "Lumen Pods have active noise cancellation."

RULES = [
    ScriptedRule("12 hours", "SUPPORTED", "up to 12 hours of playback per charge", "The fact sheet says so."),
    # The corrector re-verifies its fix; the corrected sentence must check as SUPPORTED to be offered.
    ScriptedRule("2-year warranty", "SUPPORTED", "Warranty: 2 years.", "The fact sheet says 2 years."),
    ScriptedRule("warranty", "CONTRADICTED", "Warranty: 2 years.", "The fact sheet says 2 years.",
                 correction=("5 year", "2-year")),
    ScriptedRule("noise cancellation", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions it."),
]


def _by_text(review: dict) -> dict[str, dict]:
    return {f["original_text"]: f for f in review["findings"]}


def _use_responder(monkeypatch, respond) -> ResponderProvider:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    provider = ResponderProvider(respond)
    monkeypatch.setattr(pipeline, "build_provider", lambda confidential=False, on_attempt=None: FallbackProvider(
        [("scripted", lambda: provider)], on_attempt=on_attempt or (lambda **_: None)))
    return provider


def _block(request, tag: str) -> dict:
    return json.loads(request.user.split(f"<{tag}>\n", 1)[1].rsplit(f"\n</{tag}>", 1)[0])


def _extract_each_sentence(request) -> dict:
    return {"statements": [{"sentence_id": s["id"], "kind": "factual", "claims": [{"text": s["text"], "source_quote": s["text"]}]}
                           for s in _block(request, "content_json")["sentences"]]}


# --- A successful review -------------------------------------------------------------------------


@requires_db
def test_all_three_verdicts_reach_the_review_with_provenance_and_routing(client, monkeypatch, account_factory, db_session):
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("integration")
    review = owner.submit(" ".join([SUPPORTED, CONTRADICTED, UNVERIFIED]))
    findings = _by_text(review)
    assert set(findings) == {SUPPORTED, CONTRADICTED, UNVERIFIED}

    supported, contradicted, unverified = findings[SUPPORTED], findings[CONTRADICTED], findings[UNVERIFIED]
    assert (supported["verification_status"], supported["requires_human_review"]) == ("supported", False)
    assert (contradicted["verification_status"], contradicted["requires_human_review"]) == ("contradicted", True)
    assert (unverified["verification_status"], unverified["requires_human_review"]) == ("unverified", True)
    assert review["status"] == "needs_human_review"  # anything not SUPPORTED goes to a person

    # Provenance: the cited quote is verbatim in the approved document, linked to its source and version.
    for finding, relation in ((supported, "supports"), (contradicted, "contradicts")):
        [evidence] = finding["evidence"]
        assert evidence["relation"] == relation and evidence["quote"] in DEFAULT_FACT_SHEET
        assert evidence["source_id"] == owner.source_id and evidence["source_version_id"]
        assert evidence["source_version_number"] == 1
    assert unverified["evidence"] == []  # no evidence, no citation: never "false"


@requires_db
def test_a_correction_is_traceable_to_the_cited_evidence(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, RULES)
    finding = _by_text(account_factory("correction").submit(CONTRADICTED))[CONTRADICTED]
    assert finding["suggested_correction"] == "Lumen Pods come with a 2-year warranty."
    assert "2" in finding["evidence"][0]["quote"]  # the new figure comes from the cited quote


# --- Invalid, malformed and missing model output ------------------------------------------------


@pytest.mark.parametrize("bad_reply", [
    {"verdict": "DEFINITELY_TRUE", "citations": [], "rationale": "trust me"},        # invalid verdict
    {"verdict": "SUPPORTED", "citations": "everything", "rationale": "x"},           # wrong type
    {"verdict": "SUPPORTED", "citations": []},                                       # missing field
    {"verdict": "SUPPORTED", "citations": [], "rationale": "x", "approve": True},    # extra field
    MalformedOutputError("not JSON"),                                                # not JSON at all
])
@requires_db
def test_invalid_or_malformed_verification_output_is_unverified_never_supported(client, monkeypatch, account_factory, bad_reply):
    def respond(request):
        return _extract_each_sentence(request) if request.schema_name == "claim_extraction" else bad_reply

    _use_responder(monkeypatch, respond)
    review = account_factory("malformed").submit(SUPPORTED)
    [finding] = review["findings"]
    assert finding["verification_status"] == "unverified" and finding["requires_human_review"] is True
    assert finding["evidence"] == [] and finding["suggested_correction"] is None
    assert review["status"] == "needs_human_review"


@requires_db
def test_a_fabricated_quote_is_refused_by_the_guard_and_the_backend(client, monkeypatch, account_factory):
    def respond(request):
        if request.schema_name == "claim_extraction":
            return _extract_each_sentence(request)
        label = _block(request, "verification_input_json")["passages"][0]["label"]
        return {"verdict": "SUPPORTED", "citations": [{"passage": label, "quote": "up to 99 hours of playback"}], "rationale": "x"}

    _use_responder(monkeypatch, respond)
    [finding] = account_factory("fabricated").submit(SUPPORTED)["findings"]
    assert finding["verification_status"] == "unverified" and finding["evidence"] == []


@requires_db
def test_unparseable_extraction_fails_the_review_instead_of_passing_it(client, monkeypatch, account_factory):
    _use_responder(monkeypatch, lambda request: {"wrong": "shape"})
    review = account_factory("extraction").submit(SUPPORTED)
    assert review["status"] == "failed" and review["findings"] == []


# --- Missing evidence --------------------------------------------------------------------------------


@requires_db
def test_no_approved_documents_fails_the_review_with_a_reason(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, RULES)
    review = account_factory("nosource", with_source=False).submit(SUPPORTED)
    assert review["status"] == "failed" and review["findings"] == []
    assert "no approved sources" in review["error_summary"]


# --- Provider failures and partial failures ---------------------------------------------------


@pytest.mark.parametrize("error", [ProviderTimeoutError("slow"), ProviderRateLimitError("429")])
@requires_db
def test_a_provider_failure_is_never_a_verdict_and_is_logged(client, monkeypatch, account_factory, db_session, error):
    def respond(request):
        return _extract_each_sentence(request) if request.schema_name == "claim_extraction" else error

    _use_responder(monkeypatch, respond)
    review = account_factory("provider").submit(SUPPORTED)
    [finding] = review["findings"]
    assert finding["verification_status"] == "unverified" and finding["category"] == "engine_error"
    assert finding["requires_human_review"] is True and finding["evidence"] == []
    db_session.expire_all()
    statuses = {c.status for c in db_session.query(ExternalCallLog).filter_by(review_id=uuid.UUID(review["id"]))}
    assert statuses - {"success"}  # the failure is in the external call log, without content


@requires_db
def test_one_failing_claim_leaves_the_other_claims_intact(client, monkeypatch, account_factory):
    def respond(request):
        if request.schema_name == "claim_extraction":
            return _extract_each_sentence(request)
        block = _block(request, "verification_input_json")
        if "warranty" in block["claim"]:
            return ProviderTimeoutError("slow")
        passage = next(p for p in block["passages"] if "12 hours" in p["text"])
        return {"verdict": "SUPPORTED", "citations": [{"passage": passage["label"], "quote": "up to 12 hours of playback per charge"}],
                "rationale": "Quoted."}

    _use_responder(monkeypatch, respond)
    findings = _by_text(account_factory("partial").submit(f"{SUPPORTED} {CONTRADICTED}"))
    assert findings[SUPPORTED]["verification_status"] == "supported"
    assert findings[CONTRADICTED]["verification_status"] == "unverified" and findings[CONTRADICTED]["category"] == "engine_error"


# --- Contract gaps owned by the backend (strict expected failures) -----------------------------


@pytest.mark.xfail(strict=True, reason="backend gap 1: conflicting_sources is mapped to 'unverified' (engine sets "
                   "ClaimResult.conflicting_sources; CONTRACTS.md 'Mapping to Member 3's shared values')")
@requires_db
def test_gap1_conflicting_approved_sources_are_reported_as_conflicting_sources(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, [ScriptedRule("12 hours", "SUPPORTED", "up to 12 hours of playback per charge")])
    owner = account_factory("conflict")
    owner.upload_source("Lumen Pods - Fact Sheet v3\n\nBattery life: up to 10 hours of playback per charge.\n", title="Fact Sheet v3")
    [finding] = owner.submit(SUPPORTED)["findings"]
    assert finding["requires_human_review"] is True  # holds today
    assert finding["verification_status"] == "conflicting_sources"  # fails today: "unverified"


@pytest.mark.xfail(strict=True, reason="backend gap 2: the engine's safer wording (not evidence-backed) is stored in "
                   "suggested_correction instead of a separate safer_wording field (contract decision 2026-10-24)")
@requires_db
def test_gap2_safer_wording_is_kept_out_of_suggested_correction(client, monkeypatch, account_factory):
    claim = "The Lumen Pods are India's number one earbuds."
    use_scripted_provider(monkeypatch, [ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No rankings.",
                                                     correction=("India's number one earbuds", "earbuds sold in India"))])
    [finding] = account_factory("safer").submit(claim)["findings"]
    assert finding["verification_status"] == "unverified"  # holds today
    assert finding["suggested_correction"] is None  # fails today: the softened wording is stored here
    assert finding.get("safer_wording") == "The Lumen Pods are earbuds sold in India."


@pytest.mark.xfail(strict=True, reason="backend gap 3: rules.evaluate_rules (terminology, accessibility) is not run "
                   "in reviews (RULES_HANDOFF.md)")
@requires_db
def test_gap3_rule_findings_appear_in_reviews(client, monkeypatch, account_factory):
    use_scripted_provider(monkeypatch, RULES)
    review = account_factory("rules").submit(f"BUY NOW TODAY. {SUPPORTED}")
    assert any(f["check_type"] == "rule" and f["category"] == "accessibility" for f in review["findings"])
