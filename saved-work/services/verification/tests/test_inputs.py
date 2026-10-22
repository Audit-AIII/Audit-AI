import pytest
from pydantic import ValidationError

from inkloom_verify import schemas
from inkloom_verify.schemas import InputContent, ReferenceDocument, VerificationRequest, sha256_text


@pytest.mark.parametrize("text", ["", " ", "\n\t  \r\n"])
def test_empty_content_rejected(text):
    with pytest.raises(ValidationError):
        InputContent(text=text)


def test_content_length_boundary():
    assert len(InputContent(text="a" * schemas.MAX_CONTENT_CHARS).text) == schemas.MAX_CONTENT_CHARS
    with pytest.raises(ValidationError):
        InputContent(text="a" * (schemas.MAX_CONTENT_CHARS + 1))


def test_text_is_preserved_exactly():
    text = "  Leading and trailing whitespace matter for offsets.\n"
    assert InputContent(text=text).text == text


def test_hash_is_filled_when_absent():
    assert InputContent(text="abc").text_sha256 == sha256_text("abc")
    assert ReferenceDocument(doc_id="d", text="abc").text_sha256 == sha256_text("abc")


def test_matching_hash_is_accepted_and_wrong_hash_rejected():
    assert InputContent(text="abc", text_sha256=sha256_text("abc")).text == "abc"
    with pytest.raises(ValidationError, match="does not match"):
        InputContent(text="abc", text_sha256=sha256_text("abd"))
    with pytest.raises(ValidationError, match="does not match"):
        ReferenceDocument(doc_id="d", text="abc", text_sha256=sha256_text("abd"))


def test_explicit_null_hash_rejected():
    with pytest.raises(ValidationError):
        InputContent(text="abc", text_sha256=None)


def test_unknown_fields_rejected(request_data):
    request_data["content"]["language"] = "en"
    with pytest.raises(ValidationError, match="Extra inputs"):
        VerificationRequest.model_validate(request_data)


def test_models_are_immutable(request_data):
    request = VerificationRequest.model_validate(request_data)
    with pytest.raises(ValidationError):
        request.tenant_id = "other"


def test_request_round_trip(request_data):
    request = VerificationRequest.model_validate(request_data)
    assert VerificationRequest.model_validate_json(request.model_dump_json()) == request


def test_contract_version_defaults_and_must_match(request_data):
    del request_data["contract_version"]
    assert VerificationRequest.model_validate(request_data).contract_version == schemas.CONTRACT_VERSION
    request_data["contract_version"] = "9.9.9"
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(request_data)


@pytest.mark.parametrize("field", ["request_id", "tenant_id", "content", "references"])
def test_required_request_fields(request_data, field):
    del request_data[field]
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(request_data)


def test_request_without_references_rejected(request_data):
    request_data["references"] = []
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(request_data)


def test_duplicate_reference_ids_rejected(request_data):
    duplicate = {k: v for k, v in request_data["references"][0].items() if k != "text_sha256"}
    request_data["references"].append(dict(duplicate, text="Other text."))
    with pytest.raises(ValidationError, match="duplicate reference doc_id: spec-sheet"):
        VerificationRequest.model_validate(request_data)


def test_reference_count_limit(request_data):
    refs = [{"doc_id": f"doc-{i}", "text": "t"} for i in range(schemas.MAX_REFERENCE_DOCS + 1)]
    request_data["references"] = refs[:-1]
    VerificationRequest.model_validate(request_data)
    request_data["references"] = refs
    with pytest.raises(ValidationError):
        VerificationRequest.model_validate(request_data)


def test_total_reference_size_limit(request_data, monkeypatch):
    monkeypatch.setattr(schemas, "MAX_TOTAL_REFERENCE_CHARS", 10)
    request_data["references"] = [{"doc_id": "a", "text": "x" * 5}, {"doc_id": "b", "text": "y" * 5}]
    VerificationRequest.model_validate(request_data)
    request_data["references"][1]["text"] = "y" * 6
    with pytest.raises(ValidationError, match="in total"):
        VerificationRequest.model_validate(request_data)


def test_blank_reference_text_rejected():
    with pytest.raises(ValidationError):
        ReferenceDocument(doc_id="d", text="   ")
