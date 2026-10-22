import pytest
from pydantic import ValidationError

from inkloom_verify.chunking import ChunkingConfig, chunk_document, passage_id_for
from inkloom_verify.schemas import MAX_PASSAGE_CHARS, EvidencePassage, ReferenceDocument, SourceSpan

SPEC = ReferenceDocument(
    doc_id="product-spec",
    text=(
        "Lumen Bottle Product Specification.\n"
        "\n"
        "Capacity: 750 ml\n"
        "Weight: 340 g\n"
        "Insulation: keeps drinks cold for up to 24 hours. It keeps drinks hot for up to 12 hours.\n"
        "\n"
        "Care: hand wash only, e.g. with warm water. Do not use bleach. Rated 4.5 by testers.\n"
    ),
)


def texts(passages):
    return [p.text for p in passages]


def single_sentences() -> ChunkingConfig:
    return ChunkingConfig(sentences_per_passage=1, stride=1)


def test_passage_text_is_the_exact_source_slice():
    for passage in chunk_document(SPEC, ChunkingConfig()):
        assert SPEC.text[passage.span.start : passage.span.end] == passage.text
        assert passage.text == passage.text.strip()
        assert passage.doc_id == SPEC.doc_id
        assert passage.doc_text_sha256 == SPEC.text_sha256


def test_segments_are_sentences_and_lines():
    assert texts(chunk_document(SPEC, single_sentences())) == [
        "Lumen Bottle Product Specification.",
        "Capacity: 750 ml",
        "Weight: 340 g",
        "Insulation: keeps drinks cold for up to 24 hours.",
        "It keeps drinks hot for up to 12 hours.",
        "Care: hand wash only, e.g. with warm water.",
        "Do not use bleach.",
        "Rated 4.5 by testers.",
    ]


def test_windows_slide_within_a_paragraph_but_never_cross_it():
    passages = texts(chunk_document(SPEC, ChunkingConfig(sentences_per_passage=2, stride=1)))
    assert passages[0] == "Lumen Bottle Product Specification."
    assert "Capacity: 750 ml\nWeight: 340 g" in passages
    assert "Weight: 340 g\nInsulation: keeps drinks cold for up to 24 hours." in passages
    assert not any("Specification." in p and "Capacity" in p for p in passages)
    assert not any("12 hours." in p and "Care:" in p for p in passages)


def test_no_source_text_is_lost():
    for config in [ChunkingConfig(), single_sentences(), ChunkingConfig(sentences_per_passage=3, stride=3)]:
        covered = set()
        for passage in chunk_document(SPEC, config):
            covered.update(range(passage.span.start, passage.span.end))
        missing = [i for i, ch in enumerate(SPEC.text) if not ch.isspace() and i not in covered]
        assert missing == []


def test_long_sentence_is_split_at_whitespace_within_the_limit():
    words = " ".join(f"word{i}" for i in range(200))
    document = ReferenceDocument(doc_id="long", text=words)
    passages = chunk_document(document, ChunkingConfig(sentences_per_passage=1, stride=1, max_passage_chars=100))
    assert len(passages) > 1
    assert all(len(p.text) <= 100 for p in passages)
    assert all(not p.text.startswith(" ") and not p.text.endswith(" ") for p in passages)
    assert " ".join(texts(passages)) == words


def test_unbroken_text_is_cut_at_the_limit():
    document = ReferenceDocument(doc_id="blob", text="x" * 250)
    passages = chunk_document(document, ChunkingConfig(sentences_per_passage=1, stride=1, max_passage_chars=100))
    assert [len(p.text) for p in passages] == [100, 100, 50]


def test_windows_shrink_to_fit_the_limit():
    sentence = "This sentence has exactly sixty characters in it, I promise."
    document = ReferenceDocument(doc_id="d", text=" ".join([sentence] * 3))
    passages = chunk_document(document, ChunkingConfig(sentences_per_passage=3, stride=1, max_passage_chars=130))
    assert all(len(p.text) <= 130 for p in passages)


def test_offsets_are_code_points():
    document = ReferenceDocument(doc_id="emoji", text="Loved by \U0001F600 fans. Made in Portugal.")
    passages = chunk_document(document, single_sentences())
    assert texts(passages) == ["Loved by \U0001F600 fans.", "Made in Portugal."]
    assert passages[1].span.slice(document.text) == "Made in Portugal."


def test_passages_satisfy_the_evidence_contract():
    for passage in chunk_document(SPEC, ChunkingConfig()):
        EvidencePassage(
            passage_id=passage.passage_id,
            doc_id=passage.doc_id,
            doc_text_sha256=passage.doc_text_sha256,
            span=passage.span,
            text=passage.text,
            retrieval={"method": "bm25", "score": 1.0, "rank": 1},
        )


def test_passage_ids_are_unique_and_stable():
    first = chunk_document(SPEC, ChunkingConfig())
    second = chunk_document(SPEC, ChunkingConfig())
    assert [p.passage_id for p in first] == [p.passage_id for p in second]
    assert len({p.passage_id for p in first}) == len(first)


def test_passage_ids_depend_on_document_identity_and_location():
    span = SourceSpan(start=0, end=5)
    base = passage_id_for("doc-a", "a" * 64, span)
    assert base != passage_id_for("doc-b", "a" * 64, span)
    assert base != passage_id_for("doc-a", "b" * 64, span)
    assert base != passage_id_for("doc-a", "a" * 64, SourceSpan(start=0, end=6))


def test_whitespace_padded_document():
    document = ReferenceDocument(doc_id="padded", text="\n\n   Only one sentence here.   \n\n")
    [passage] = chunk_document(document, ChunkingConfig())
    assert passage.text == "Only one sentence here."
    assert passage.span == SourceSpan(start=5, end=28)


@pytest.mark.parametrize(
    "settings",
    [
        {"sentences_per_passage": 1, "stride": 2},
        {"sentences_per_passage": 0},
        {"max_passage_chars": 49},
        {"max_passage_chars": MAX_PASSAGE_CHARS + 1},
        {"stride": True},
        {"unknown": 1},
    ],
)
def test_invalid_chunking_config(settings):
    with pytest.raises(ValidationError):
        ChunkingConfig(**settings)
