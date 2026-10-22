"""The documented payloads must stay valid and consistent with each other, and the exported
JSON Schema files must match the models."""

import pytest

from inkloom_verify.json_schema import DEFAULT_OUT_DIR, EXPORTED_MODELS, render
from inkloom_verify.schemas import ReferenceDocument, VerificationReport, VerificationRequest


@pytest.fixture
def request_model(request_data) -> VerificationRequest:
    return VerificationRequest.model_validate(request_data)


@pytest.fixture
def report_model(report_data) -> VerificationReport:
    return VerificationReport.model_validate(report_data)


def test_report_answers_the_example_request(request_model, report_model):
    assert report_model.request_id == request_model.request_id
    assert report_model.tenant_id == request_model.tenant_id
    assert report_model.content_sha256 == request_model.content.text_sha256
    assert report_model.content_length == len(request_model.content.text)
    assert report_model.references == [r.descriptor() for r in request_model.references]


def test_report_evidence_and_citations_match_the_original_documents(request_model, report_model):
    documents: dict[str, ReferenceDocument] = {d.doc_id: d for d in request_model.references}
    for result in report_model.results:
        for passage in result.evidence:
            assert passage.matches(documents[passage.doc_id])
        for citation in result.citations:
            assert citation.matches(documents[citation.doc_id])


def test_report_corrections_match_the_original_content(request_model, report_model):
    text = request_model.content.text
    corrections = [r.correction for r in report_model.results if r.correction is not None]
    assert corrections
    for correction in corrections:
        assert correction.target_span.slice(text) == correction.original_text


def test_claim_spans_fall_inside_the_content(request_model, report_model):
    for result in report_model.results:
        assert result.claim.source_span.slice(request_model.content.text).strip()


@pytest.mark.parametrize("name", sorted(EXPORTED_MODELS))
def test_committed_json_schema_is_current(name):
    committed = (DEFAULT_OUT_DIR / f"{name}.schema.json").read_text(encoding="utf-8")
    assert committed == render(EXPORTED_MODELS[name]), "run: python -m inkloom_verify.json_schema"
