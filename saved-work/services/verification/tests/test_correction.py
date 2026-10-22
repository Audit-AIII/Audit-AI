import pytest
from pydantic import ValidationError

from inkloom_verify.schemas import Correction, numbers_in


@pytest.fixture
def correction(contradicted_result) -> dict:
    return contradicted_result["correction"]


def test_example_correction_is_valid(correction):
    assert Correction.model_validate(correction).replacement_text == "70%"


def test_replacement_must_change_the_text(correction):
    correction["replacement_text"] = correction["original_text"]
    with pytest.raises(ValidationError, match="must differ"):
        Correction.model_validate(correction)


def test_number_absent_from_evidence_rejected(correction):
    correction["replacement_text"] = "75%"
    with pytest.raises(ValidationError, match="not found in any cited quote: 75"):
        Correction.model_validate(correction)


def test_requires_citations(correction):
    correction["citations"] = []
    with pytest.raises(ValidationError):
        Correction.model_validate(correction)


def test_original_text_must_fill_target_span(correction):
    correction["original_text"] = "90 %"
    with pytest.raises(ValidationError, match="does not match target_span"):
        Correction.model_validate(correction)


def test_blank_replacement_rejected(correction):
    correction["replacement_text"] = " "
    with pytest.raises(ValidationError):
        Correction.model_validate(correction)


def test_numbers_kept_from_the_original_need_no_new_support(correction):
    Correction(
        target_span={"start": 0, "end": 10},
        original_text="about 90 g",
        replacement_text="90 grams",
        citations=correction["citations"],
    )


def test_thousands_separators_are_normalised():
    assert numbers_in("1,200 units and 3.5 kg in 2015") == {"1200", "3.5", "2015"}
