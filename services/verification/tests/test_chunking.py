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
    return ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1)


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
    passages = texts(chunk_document(SPEC, ChunkingConfig(strategy="sentences", sentences_per_passage=2, stride=1)))
    assert passages[0] == "Lumen Bottle Product Specification."
    assert "Capacity: 750 ml\nWeight: 340 g" in passages
    assert "Weight: 340 g\nInsulation: keeps drinks cold for up to 24 hours." in passages
    assert not any("Specification." in p and "Capacity" in p for p in passages)
    assert not any("12 hours." in p and "Care:" in p for p in passages)


def test_no_source_text_is_lost():
    for config in [ChunkingConfig(), single_sentences(), ChunkingConfig(strategy="sentences", sentences_per_passage=3, stride=3)]:
        covered = set()
        for passage in chunk_document(SPEC, config):
            covered.update(range(passage.span.start, passage.span.end))
        missing = [i for i, ch in enumerate(SPEC.text) if not ch.isspace() and i not in covered]
        assert missing == []


def test_long_sentence_is_split_at_whitespace_within_the_limit():
    words = " ".join(f"word{i}" for i in range(200))
    document = ReferenceDocument(doc_id="long", text=words)
    passages = chunk_document(document, ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1, max_passage_chars=100))
    assert len(passages) > 1
    assert all(len(p.text) <= 100 for p in passages)
    assert all(not p.text.startswith(" ") and not p.text.endswith(" ") for p in passages)
    assert " ".join(texts(passages)) == words


def test_unbroken_text_is_cut_at_the_limit():
    document = ReferenceDocument(doc_id="blob", text="x" * 250)
    passages = chunk_document(document, ChunkingConfig(strategy="sentences", sentences_per_passage=1, stride=1, max_passage_chars=100))
    assert [len(p.text) for p in passages] == [100, 100, 50]


def test_windows_shrink_to_fit_the_limit():
    sentence = "This sentence has exactly sixty characters in it, I promise."
    document = ReferenceDocument(doc_id="d", text=" ".join([sentence] * 3))
    passages = chunk_document(document, ChunkingConfig(strategy="sentences", sentences_per_passage=3, stride=1, max_passage_chars=130))
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
        {"strategy": "sentences", "sentences_per_passage": 1, "stride": 2},
        {"strategy": "sentences", "sentences_per_passage": 0},
        {"strategy": "sentences", "max_passage_chars": 49},
        {"strategy": "sentences", "max_passage_chars": MAX_PASSAGE_CHARS + 1},
        {"strategy": "sentences", "stride": True},
        {"unknown": 1},
        {"strategy": "words"},
        {"min_tokens": 300, "target_tokens": 250},  # min > target
        {"target_tokens": 450, "max_tokens": 400},  # target > max
        {"overlap_tokens": 200},  # overlap must be < min
        {"max_tokens": True},
        {"sentences_per_passage": 2},  # sentence setting under the tokens strategy
        {"strategy": "sentences", "target_tokens": 300},  # token setting under the sentences strategy
    ],
)
def test_invalid_chunking_config(settings):
    with pytest.raises(ValidationError):
        ChunkingConfig(**settings)


# --- "tokens" strategy (the default): 200-400 token chunks with overlap -------------------------

LONG = ReferenceDocument(
    doc_id="handbook",
    text="\n\n".join(
        " ".join(f"Section {p} fact {i}: the item weighs {p * 10 + i} grams and ships in box {i}." for i in range(14))
        for p in range(1, 9)
    ),
)


def word_count(text: str) -> int:
    return len(text.split())


def test_tokens_is_the_default_strategy():
    assert ChunkingConfig().strategy == "tokens"
    assert (ChunkingConfig().min_tokens, ChunkingConfig().target_tokens, ChunkingConfig().max_tokens) == (200, 300, 400)


def test_token_chunks_are_within_bounds_and_exact():
    passages = chunk_document(LONG, ChunkingConfig())
    assert len(passages) > 3
    for passage in passages:
        assert LONG.text[passage.span.start : passage.span.end] == passage.text
        assert passage.text == passage.text.strip()
        assert 200 <= word_count(passage.text) <= 400
        assert len(passage.text) <= MAX_PASSAGE_CHARS


def test_token_chunks_overlap_by_whole_sentences():
    passages = chunk_document(LONG, ChunkingConfig())
    for before, after in zip(passages, passages[1:]):
        assert after.span.start < before.span.end  # they overlap
        shared = LONG.text[after.span.start : before.span.end]
        assert word_count(shared) >= 50
        assert shared.startswith("Section")  # starts on a sentence boundary


def test_token_chunks_lose_no_text():
    covered = set()
    for passage in chunk_document(LONG, ChunkingConfig()):
        covered.update(range(passage.span.start, passage.span.end))
    assert [i for i, ch in enumerate(LONG.text) if not ch.isspace() and i not in covered] == []


def test_token_chunks_cross_paragraph_breaks():
    assert any("\n\n" in p.text for p in chunk_document(LONG, ChunkingConfig()))


def test_short_document_is_a_single_chunk():
    [passage] = chunk_document(SPEC, ChunkingConfig())
    assert passage.text == SPEC.text.strip()


def test_overlong_sentence_is_cut_into_token_windows():
    document = ReferenceDocument(doc_id="run-on", text=" ".join(f"w{i}" for i in range(1_000)))
    passages = chunk_document(document, ChunkingConfig())
    assert all(word_count(p.text) <= 400 for p in passages)
    assert passages[0].text.split()[0] == "w0" and passages[-1].text.split()[-1] == "w999"


def test_character_cap_holds_for_very_long_words():
    document = ReferenceDocument(doc_id="urls", text=" ".join("https://example.com/" + "x" * 60 for _ in range(300)))
    assert all(len(p.text) <= MAX_PASSAGE_CHARS for p in chunk_document(document, ChunkingConfig()))


def test_final_chunk_is_extended_to_the_minimum():
    last = chunk_document(LONG, ChunkingConfig())[-1]
    assert word_count(last.text) >= 200 and last.span.end == len(LONG.text.rstrip())


def test_custom_token_sizes():
    passages = chunk_document(LONG, ChunkingConfig(min_tokens=40, target_tokens=60, max_tokens=80, overlap_tokens=10))
    assert all(word_count(p.text) <= 80 for p in passages) and len(passages) > 10


def test_token_chunk_ids_are_stable():
    assert [p.passage_id for p in chunk_document(LONG, ChunkingConfig())] == [
        p.passage_id for p in chunk_document(LONG, ChunkingConfig())
    ]


def test_chunks_stop_at_the_target_not_the_maximum():
    sentence_tokens = max(word_count(s) for s in LONG.text.replace("\n\n", " ").split(". "))
    for passage in chunk_document(LONG, ChunkingConfig())[:-1]:
        assert 300 <= word_count(passage.text) < 300 + sentence_tokens + 1


def test_a_short_tail_is_extended_backwards_to_the_minimum():
    # 33 ten-word sentences: the first chunk takes 30; on its own the tail would be ~50 tokens.
    document = ReferenceDocument(doc_id="tail", text=" ".join(f"Sentence {i:02d} has exactly ten words in it today, see." for i in range(33)))
    passages = chunk_document(document, ChunkingConfig())
    assert len(passages) == 2
    assert word_count(passages[-1].text) >= 200
    assert passages[-1].span.end == len(document.text)
