"""Splits reference documents into passages that can be traced back to their source.

Strategy (see CONTRACTS.md, "Retrieval"):

1. Split the document into paragraphs at blank lines.
2. Split each paragraph into segments: sentences, and single lines (so bullet lists and
   spec tables without punctuation still become separate segments).
3. Split any segment longer than ``max_passage_chars`` at whitespace.
4. Group consecutive segments of one paragraph into windows of ``sentences_per_passage``,
   moving forward by ``stride`` segments, and shrink a window until it fits
   ``max_passage_chars``.

Passage text is always the exact slice ``document.text[span.start:span.end]`` with surrounding
whitespace excluded from the span. Nothing is rewritten, normalised or generated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkloom_verify.schemas import MAX_PASSAGE_CHARS, ReferenceDocument, SourceSpan

_PARAGRAPH_BREAK = re.compile(r"\n[ \t\r\f\v]*\n")
_LINE_BREAK = re.compile(r"\n")
# A sentence ends at . ! ? or an ellipsis, optionally followed by closing quotes or brackets,
# when whitespace follows.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)")
_ABBREVIATIONS = frozenset(
    {"e.g.", "i.e.", "etc.", "vs.", "inc.", "ltd.", "co.", "corp.", "mr.", "mrs.", "ms.", "dr.", "st.", "no.", "approx."}
)


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sentences_per_passage: Annotated[int, Field(strict=True, ge=1, le=10)] = 2
    stride: Annotated[int, Field(strict=True, ge=1, le=10)] = 1
    max_passage_chars: Annotated[int, Field(strict=True, ge=50, le=MAX_PASSAGE_CHARS)] = 1_000

    @model_validator(mode="after")
    def _check_stride(self) -> ChunkingConfig:
        if self.stride > self.sentences_per_passage:
            raise ValueError("stride must not exceed sentences_per_passage, or text would be skipped")
        return self


@dataclass(frozen=True)
class DocumentPassage:
    """A passage before retrieval: where it is and what it says, with no score."""

    passage_id: str
    doc_id: str
    doc_text_sha256: str
    span: SourceSpan
    text: str
    doc_order: int  # position of the document in the corpus, for deterministic tie-breaking


def passage_id_for(doc_id: str, doc_text_sha256: str, span: SourceSpan) -> str:
    """A passage id that depends only on the document and location, so it is stable across runs."""
    key = f"{doc_id}\x00{doc_text_sha256}\x00{span.start}\x00{span.end}".encode("utf-8")
    return "psg_" + hashlib.sha256(key).hexdigest()[:24]


def _trimmed(text: str, start: int, end: int) -> tuple[int, int] | None:
    """The [start, end) range with surrounding whitespace removed, or None if nothing remains."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _split_at(pattern: re.Pattern[str], text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Splits [start, end) at each match of ``pattern``, dropping the separators."""
    pieces = []
    cursor = start
    for match in pattern.finditer(text, start, end):
        pieces.append((cursor, match.start()))
        cursor = match.end()
    pieces.append((cursor, end))
    return [trimmed for s, e in pieces if (trimmed := _trimmed(text, s, e)) is not None]


def _is_abbreviation(text: str, end: int) -> bool:
    word_start = end
    while word_start > 0 and not text[word_start - 1].isspace():
        word_start -= 1
    return text[word_start:end].casefold() in _ABBREVIATIONS


def _sentences(text: str, start: int, end: int) -> list[tuple[int, int]]:
    pieces = []
    cursor = start
    for match in _SENTENCE_END.finditer(text, start, end):
        if _is_abbreviation(text, match.end()):
            continue
        pieces.append((cursor, match.end()))
        cursor = match.end()
    pieces.append((cursor, end))
    return [trimmed for s, e in pieces if (trimmed := _trimmed(text, s, e)) is not None]


def _fit(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    """Splits one segment into pieces of at most ``limit`` characters, preferring whitespace."""
    pieces = []
    while end - start > limit:
        cut = start + limit
        space = max(text.rfind(" ", start + 1, cut + 1), text.rfind("\t", start + 1, cut + 1))
        if space > start:
            cut = space
        if (piece := _trimmed(text, start, cut)) is not None:
            pieces.append(piece)
        start = cut
    if (piece := _trimmed(text, start, end)) is not None:
        pieces.append(piece)
    return pieces


def _segments(text: str, start: int, end: int, limit: int) -> list[tuple[int, int]]:
    segments = []
    for line_start, line_end in _split_at(_LINE_BREAK, text, start, end):
        for sentence_start, sentence_end in _sentences(text, line_start, line_end):
            segments.extend(_fit(text, sentence_start, sentence_end, limit))
    return segments


def sentence_spans(text: str, max_chars: int) -> list[SourceSpan]:
    """Every sentence or line of ``text`` in order, split at whitespace when longer than ``max_chars``.

    The same segmentation passages are built from, exposed for claim extraction.
    """
    return [
        SourceSpan(start=start, end=end)
        for para_start, para_end in _split_at(_PARAGRAPH_BREAK, text, 0, len(text))
        for start, end in _segments(text, para_start, para_end, max_chars)
    ]


def _window_starts(count: int, size: int, stride: int) -> list[int]:
    if count <= size:
        return [0]
    starts = list(range(0, count - size + 1, stride))
    if starts[-1] + size < count:
        starts.append(count - size)
    return starts


def chunk_document(document: ReferenceDocument, config: ChunkingConfig, doc_order: int = 0) -> list[DocumentPassage]:
    """All passages of one document, in document order, without duplicate spans."""
    text = document.text
    spans: list[tuple[int, int]] = []
    for para_start, para_end in _split_at(_PARAGRAPH_BREAK, text, 0, len(text)):
        segments = _segments(text, para_start, para_end, config.max_passage_chars)
        for first in _window_starts(len(segments), config.sentences_per_passage, config.stride):
            last = min(first + config.sentences_per_passage, len(segments)) - 1
            while segments[last][1] - segments[first][0] > config.max_passage_chars:
                last -= 1
            spans.append((segments[first][0], segments[last][1]))

    passages = []
    seen: set[tuple[int, int]] = set()
    for start, end in spans:
        if (start, end) in seen:
            continue
        seen.add((start, end))
        span = SourceSpan(start=start, end=end)
        passages.append(
            DocumentPassage(
                passage_id=passage_id_for(document.doc_id, document.text_sha256, span),
                doc_id=document.doc_id,
                doc_text_sha256=document.text_sha256,
                span=span,
                text=text[start:end],
                doc_order=doc_order,
            )
        )
    return passages
