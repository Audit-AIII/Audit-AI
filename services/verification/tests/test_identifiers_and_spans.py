import pytest
from pydantic import ValidationError

from inkloom_verify.schemas import Claim, EvidencePassage, ReferenceDocument, SourceSpan


@pytest.mark.parametrize("doc_id", ["a", "spec-sheet", "Doc_1.v2:final", "x" * 128])
def test_valid_external_ids(doc_id):
    assert ReferenceDocument(doc_id=doc_id, text="t").doc_id == doc_id


@pytest.mark.parametrize(
    "doc_id",
    ["", " ", "-leading", ".hidden", "../etc/passwd", "a/b", "has space", "new\nline", "x" * 129, "naïve"],
)
def test_invalid_external_ids(doc_id):
    with pytest.raises(ValidationError):
        ReferenceDocument(doc_id=doc_id, text="t")


@pytest.mark.parametrize("claim_id", ["clm_", "psg_0001", "0001", "clm_a b", "CLM_1", "clm_" + "a" * 65])
def test_invalid_claim_ids(claim_id):
    with pytest.raises(ValidationError):
        Claim(claim_id=claim_id, text="A claim.", source_span={"start": 0, "end": 1})


def test_claim_id_is_rejected_as_passage_id(supported_result):
    passage = dict(supported_result["evidence"][0], passage_id="clm_0001")
    with pytest.raises(ValidationError):
        EvidencePassage.model_validate(passage)


@pytest.mark.parametrize(
    "span",
    [
        {"start": 5, "end": 5},
        {"start": 6, "end": 5},
        {"start": -1, "end": 5},
        {"start": True, "end": 5},
        {"start": "0", "end": 5},
        {"start": 0.0, "end": 5},
        {"start": 0},
    ],
)
def test_invalid_spans(span):
    with pytest.raises(ValidationError):
        SourceSpan.model_validate(span)


def test_span_strictness_also_applies_to_json():
    with pytest.raises(ValidationError):
        SourceSpan.model_validate_json('{"start": "0", "end": 3}')
    assert SourceSpan.model_validate_json('{"start": 0, "end": 3}').length == 3


def test_span_helpers():
    outer = SourceSpan(start=2, end=10)
    assert outer.contains(SourceSpan(start=2, end=10))
    assert outer.contains(SourceSpan(start=3, end=4))
    assert not outer.contains(SourceSpan(start=1, end=4))
    assert not outer.contains(SourceSpan(start=9, end=11))
    assert outer.fits(10) and not outer.fits(9)
    assert SourceSpan(start=1, end=3).slice("abcd") == "bc"


def test_offsets_are_code_points():
    text = "Rated 5\u2605 by \U0001F600 users"
    star = text.index("\u2605")
    assert SourceSpan(start=star, end=star + 1).slice(text) == "\u2605"
    emoji = text.index("\U0001F600")
    assert SourceSpan(start=emoji, end=emoji + 1).slice(text) == "\U0001F600"
