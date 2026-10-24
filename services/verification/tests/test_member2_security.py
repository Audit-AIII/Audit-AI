"""Member 2 playbook security list, end to end through the engine pipeline and the backend mapping
helper (integration.finding_fields). Scripted model only, no network.

Adds what the audit of 2026-10-24 found missing at pipeline level:

* every verification failure mode (timeout, rate limit, invalid JSON, wrong field types, extra
  fields, an unknown verdict) ends as ERROR -> "unverified" with human review, never "supported";
* a fabricated passage label or quote is downgraded, never accepted;
* conflicting approved sources, including an outdated version sent next to the current one,
  surface as "conflicting_sources" with human review, never as a silent pick of one version.

Content injection, malicious reference text, cross-tenant isolation and fabricated document ids
are covered in test_pipeline.py, test_prompt_security.py, test_citation_guard.py and
test_scope.py; the backend's own copies in services/api/tests/test_security_controls.py.
"""

from __future__ import annotations

import pytest

from e2e_support import DOCS, SUPPORTED_CLAIM, RoutedProvider, careful_model, data_block, request
from inkloom_verify.integration import finding_fields
from inkloom_verify.pipeline import verify_request
from inkloom_verify.providers.base import (
    MalformedOutputError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from inkloom_verify.schemas import ReferenceDocument, ReportStatus, Verdict, VerificationRequest
from test_pipeline import failing_at

FAILURES = {
    "timeout": ProviderTimeoutError("slow"),
    "rate limit": ProviderRateLimitError("429"),
    "invalid JSON": MalformedOutputError("not JSON"),
    "unknown verdict": {"verdict": "DEFINITELY_TRUE", "citations": [], "rationale": "trust me"},
    "citations wrong type": {"verdict": "SUPPORTED", "citations": "all of them", "rationale": "x"},
    "quote wrong type": {
        "verdict": "SUPPORTED",
        "citations": [{"passage": "P1", "quote": 123}],
        "rationale": "x",
    },
    "missing field": {"verdict": "SUPPORTED", "citations": []},
    "extra field (action)": {
        "verdict": "SUPPORTED",
        "citations": [],
        "rationale": "x",
        "approve_review": True,
    },
}


@pytest.mark.parametrize("name", sorted(FAILURES))
def test_every_verification_failure_is_an_error_for_a_person_never_a_pass(name):
    report = verify_request(
        request(SUPPORTED_CLAIM), RoutedProvider(failing_at("claim_verification", FAILURES[name]))
    )
    [result] = report.results
    assert result.verdict is Verdict.ERROR and result.citations == [], name
    assert report.status is ReportStatus.PARTIAL and report.score.requires_human_review
    fields = finding_fields(result, SUPPORTED_CLAIM)
    assert fields["verification_status"] == "unverified" and fields["requires_human_review"] is True
    assert fields["suggested_correction"] is None and fields["evidence"] == []


@pytest.mark.parametrize(
    "citation",
    [
        {
            "passage": "P99",
            "quote": "up to 12 hours of playback per charge",
        },  # fabricated passage label
        {"passage": "P1", "quote": "up to 99 hours of playback per charge"},  # fabricated quote
    ],
)
def test_fabricated_citations_are_downgraded_never_accepted(citation):
    def model(req):
        if req.schema_name == "claim_verification":
            return {"verdict": "SUPPORTED", "citations": [citation], "rationale": "Quoted."}
        return careful_model(req)

    [result] = verify_request(request(SUPPORTED_CLAIM), RoutedProvider(model)).results
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.citation_guard.downgraded
    assert finding_fields(result, SUPPORTED_CLAIM)["verification_status"] == "unverified"


SHEET = DOCS["pods-fact-sheet"]
OUTDATED = ReferenceDocument(
    doc_id="pods-fact-sheet-v1",
    version="1",
    text="Lumen Pods - Product Fact Sheet (version 1)\n\nBattery life: up to 10 hours of playback per charge.",
)


def _supported_by_current_sheet(req):
    if req.schema_name == "claim_verification":
        # The model quotes the current sheet's figure and ignores the outdated one.
        passages = data_block(req, "verification_input_json")["passages"]
        label = next(
            p["label"] for p in passages if "up to 12 hours of playback per charge" in p["text"]
        )
        return {
            "verdict": "SUPPORTED",
            "citations": [{"passage": label, "quote": "up to 12 hours of playback per charge"}],
            "rationale": "The fact sheet says so.",
        }
    return careful_model(req)


def test_an_outdated_version_sent_with_the_current_one_is_a_conflict_for_a_person():
    """The engine never silently picks one version: the backend should send only the latest
    approved version (services/api latest_approved_sources); if an outdated one slips in and
    disagrees, the claim is flagged conflicting_sources and goes to review."""
    req = VerificationRequest(
        request_id="req-outdated-1",
        tenant_id="tenant-demo",
        content={"text": SUPPORTED_CLAIM},
        references=[SHEET, OUTDATED],
    )
    [result] = verify_request(req, RoutedProvider(_supported_by_current_sheet)).results
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.conflicting_sources is True
    fields = finding_fields(result, SUPPORTED_CLAIM)
    assert (
        fields["verification_status"] == "conflicting_sources"
        and fields["requires_human_review"] is True
    )
    assert fields["suggested_correction"] is None


def test_the_same_claim_with_only_the_current_version_is_supported():
    req = VerificationRequest(
        request_id="req-current-1",
        tenant_id="tenant-demo",
        content={"text": SUPPORTED_CLAIM},
        references=[SHEET],
    )
    [result] = verify_request(req, RoutedProvider(_supported_by_current_sheet)).results
    assert result.verdict is Verdict.SUPPORTED and result.conflicting_sources is False
