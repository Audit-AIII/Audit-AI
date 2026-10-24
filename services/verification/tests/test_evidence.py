import pytest
from pydantic import ValidationError

from inkloom_verify import schemas
from inkloom_verify.schemas import (
    Citation,
    ClaimVerificationInput,
    EvidencePassage,
    ReferenceDocument,
)


@pytest.fixture
def document(request_data) -> ReferenceDocument:
    return ReferenceDocument.model_validate(request_data["references"][0])


@pytest.fixture
def passage(supported_result) -> dict:
    return supported_result["evidence"][0]


@pytest.fixture
def citation(supported_result) -> dict:
    return supported_result["citations"][0]


def test_passage_and_citation_match_their_source(document, passage, citation):
    assert EvidencePassage.model_validate(passage).matches(document)
    assert Citation.model_validate(citation).matches(document)


def test_passage_does_not_match_an_edited_document(document, passage):
    edited = ReferenceDocument(doc_id=document.doc_id, text=document.text.replace("24", "48"))
    assert not EvidencePassage.model_validate(passage).matches(edited)


def test_passage_does_not_match_another_document(document, passage):
    other = ReferenceDocument(doc_id="other-doc", text=document.text)
    assert not EvidencePassage.model_validate(passage).matches(other)


def test_span_past_end_of_document_does_not_match(passage):
    short = ReferenceDocument(doc_id="spec-sheet", text="Too short.")
    assert not EvidencePassage.model_validate(
        dict(passage, doc_text_sha256=short.text_sha256)
    ).matches(short)


def test_passage_text_must_fill_its_span(passage):
    with pytest.raises(ValidationError, match="does not match its span"):
        EvidencePassage.model_validate(dict(passage, text=passage["text"] + " "))


def test_citation_quote_must_fill_its_span(citation):
    with pytest.raises(ValidationError, match="does not match quote_span"):
        Citation.model_validate(dict(citation, quote=citation["quote"][:-1]))


@pytest.mark.parametrize("score", [float("nan"), float("inf")])
def test_non_finite_retrieval_score_rejected(passage, score):
    with pytest.raises(ValidationError):
        EvidencePassage.model_validate(
            dict(passage, retrieval=dict(passage["retrieval"], score=score))
        )


def test_unknown_retrieval_method_rejected(passage):
    with pytest.raises(ValidationError):
        EvidencePassage.model_validate(
            dict(passage, retrieval=dict(passage["retrieval"], method="vector"))
        )


def test_verifier_input_holds_one_claim_and_its_passages(supported_result, passage):
    verifier_input = ClaimVerificationInput(claim=supported_result["claim"], passages=[passage])
    assert set(ClaimVerificationInput.model_fields) == {"claim", "passages"}
    assert len(verifier_input.passages) == 1


def test_verifier_input_rejects_the_reference_corpus(supported_result, passage, request_data):
    with pytest.raises(ValidationError, match="Extra inputs"):
        ClaimVerificationInput(
            claim=supported_result["claim"],
            passages=[passage],
            references=request_data["references"],
        )


def test_verifier_input_requires_passages(supported_result):
    with pytest.raises(ValidationError):
        ClaimVerificationInput(claim=supported_result["claim"], passages=[])


def test_verifier_input_passage_limit(supported_result, passage):
    passages = [
        dict(passage, passage_id=f"psg_{i}") for i in range(schemas.MAX_PASSAGES_PER_CLAIM + 1)
    ]
    ClaimVerificationInput(claim=supported_result["claim"], passages=passages[:-1])
    with pytest.raises(ValidationError):
        ClaimVerificationInput(claim=supported_result["claim"], passages=passages)


def test_verifier_input_rejects_duplicate_passages(supported_result, passage):
    with pytest.raises(ValidationError, match="duplicate passage_id"):
        ClaimVerificationInput(claim=supported_result["claim"], passages=[passage, passage])
