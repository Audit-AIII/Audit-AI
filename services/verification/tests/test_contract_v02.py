"""Contract 0.2.0 (approved in Phase 1): a claim's text is exactly the content at its source_span,
a standalone rewording lives in normalized_text, and evidence passages may name their reference
set, which must be the request's."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from inkloom_verify.extraction import ClaimExtractor
from inkloom_verify.providers.fake import ResponderProvider
from inkloom_verify.schemas import CONTRACT_VERSION, Claim, ClaimResult, VerificationReport, VerificationRequest
from inkloom_verify.scope import ScopeViolation, check_report_scope, report_violations, result_violations

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


REQUEST = VerificationRequest.model_validate(load("verification_request.json"))
CONTENT = REQUEST.content.text


def report_data() -> dict:
    return load("verification_report.json")


# --- Version ------------------------------------------------------------------------------------


def test_contract_version_is_0_2_0_and_older_payloads_are_refused():
    assert CONTRACT_VERSION == "0.2.0"
    old = load("verification_request.json") | {"contract_version": "0.1.0"}
    with pytest.raises(ValidationError, match="contract_version"):
        VerificationRequest.model_validate(old)


# --- Claim text is the content slice -------------------------------------------------------------


def test_claim_text_must_have_its_spans_length():
    with pytest.raises(ValidationError, match="exact content slice"):
        Claim(claim_id="clm_0001", text="The Lumen Bottle holds 750 ml.", source_span={"start": 0, "end": 16})


def test_rewording_lives_in_normalized_text_and_is_what_gets_checked():
    claim = Claim(claim_id="clm_0001", text="It holds 750 ml.", source_span={"start": 37, "end": 53},
                  normalized_text="The Lumen Bottle holds 750 ml.")
    assert claim.statement == "The Lumen Bottle holds 750 ml."
    plain = Claim(claim_id="clm_0002", text="It holds 750 ml.", source_span={"start": 37, "end": 53})
    assert plain.normalized_text is None and plain.statement == plain.text


def test_normalized_text_repeating_text_is_refused():
    with pytest.raises(ValidationError, match="normalized_text must differ"):
        Claim(claim_id="clm_0001", text="It holds 750 ml.", source_span={"start": 0, "end": 16},
              normalized_text="It holds 750 ml.")


def test_example_report_claims_are_exact_slices_of_the_example_content():
    report = VerificationReport.model_validate(report_data())
    for result in report.results:
        assert result.claim.source_span.slice(CONTENT) == result.claim.text
    reworded = [r.claim for r in report.results if r.claim.normalized_text]
    assert [c.claim_id for c in reworded] == ["clm_0002"]  # "It is made from ..." -> "The Lumen Bottle is made from ..."
    check_report_scope(REQUEST, report)


def test_scope_check_rejects_same_length_text_that_is_not_the_content():
    data = report_data()
    claim = data["results"][0]["claim"]
    claim["text"] = claim["text"].replace("24", "48")  # same length, different words
    report = VerificationReport.model_validate(data)  # the contract alone cannot see the content
    assert any("text is not the content at its source_span" in v for v in report_violations(REQUEST, report))
    with pytest.raises(ScopeViolation):
        check_report_scope(REQUEST, report)


def test_extractor_keeps_the_source_text_and_moves_the_rewording():
    text = "The Lumen Bottle is our new product. It holds 750 ml."

    def respond(request):
        sentences = json.loads(request.user.split("<content_json>\n", 1)[1].rsplit("\n</content_json>", 1)[0])["sentences"]
        statements = []
        for s in sentences:
            if s["text"].startswith("It holds"):
                statements.append({"sentence_id": s["id"], "kind": "factual",
                                   "claims": [{"text": "The Lumen Bottle holds 750 ml.", "source_quote": "It holds 750 ml."}]})
            else:
                statements.append({"sentence_id": s["id"], "kind": "factual",
                                   "claims": [{"text": s["text"], "source_quote": s["text"]}]})
        return {"statements": statements}

    result = ClaimExtractor(ResponderProvider(respond)).extract(text)
    first, second = result.claims
    assert (first.text, first.normalized_text) == ("The Lumen Bottle is our new product.", None)
    assert (second.text, second.normalized_text) == ("It holds 750 ml.", "The Lumen Bottle holds 750 ml.")
    for claim in result.claims:
        assert text[claim.source_span.start:claim.source_span.end] == claim.text


# --- Passages name the request's reference set ---------------------------------------------------


def test_passage_reference_set_is_optional_and_may_match_the_report():
    data = report_data()
    data["results"][0]["evidence"][0]["reference_set_id"] = data["reference_set_id"]
    report = VerificationReport.model_validate(data)
    check_report_scope(REQUEST, report)
    assert VerificationReport.model_validate(report_data()).results[0].evidence[0].reference_set_id is None


def test_report_rejects_a_passage_from_another_reference_set():
    data = report_data()
    data["results"][0]["evidence"][0]["reference_set_id"] = "refset-other-brand"
    with pytest.raises(ValidationError, match="another reference set"):
        VerificationReport.model_validate(data)


def test_scope_check_rejects_a_passage_from_another_reference_set():
    """Per result, against the request: the check the backend runs before saving."""
    data = report_data()["results"][0]
    data["evidence"][0]["reference_set_id"] = "refset-other-brand"
    result = ClaimResult.model_validate(data)
    assert any("is from another reference set" in v for v in result_violations(REQUEST, result))
    data["evidence"][0]["reference_set_id"] = REQUEST.reference_set_id
    assert result_violations(REQUEST, ClaimResult.model_validate(data)) == []
