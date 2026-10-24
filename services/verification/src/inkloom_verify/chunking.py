"""Splits reference documents into passages that can be traced back to their source.

Both strategies start the same way (see CONTRACTS.md, "Retrieval"): split the document into
paragraphs at blank lines, then into segments (sentences, and single lines so bullet lists and
spec tables without punctuation still become separate segments).

``tokens`` (the default) packs consecutive segments into chunks of about ``target_tokens``
tokens, never more than ``max_tokens``, and starts each chunk at least ``overlap_tokens`` tokens
before the previous one ended. Chunks may cross paragraph breaks. Chunk edges fall on segment
edges, so overlap is whole sentences; a single segment longer than ``max_tokens`` is cut into
token windows first. The last chunk of a document is extended backwards to at least
``min_tokens`` where the document allows. A document shorter than ``min_tokens`` is one chunk.
Tokens are whitespace-separated words: an approximation of model tokens (roughly 1.3 model
tokens per English word), chosen so chunking needs no tokenizer dependency.

``sentences`` groups ``sentences_per_passage`` consecutive segments of one paragraph, moving by
``stride`` and shrinking a window to fit ``max_passage_chars``.

Passage text is always the exact slice ``document.text[span.start:span.end]`` with surrounding
whitespace excluded from the span. Nothing is rewritten, normalised or generated.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from inkloom_verify.schemas import MAX_PASSAGE_CHARS, ReferenceDocument, SourceSpan

_PARAGRAPH_BREAK = re.compile(r"\n[ \t\r\f\v]*\n")
_LINE_BREAK = re.compile(r"\n")
# A sentence ends at . ! ? or an ellipsis, optionally followed by closing quotes or brackets,
# when whitespace follows.
_SENTENCE_END = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)")
_WORD_TOKEN = re.compile(r"\S+")
_ABBREVIATIONS = frozenset(
    {
        "e.g.",
        "i.e.",
        "etc.",
        "vs.",
        "inc.",
        "ltd.",
        "co.",
        "corp.",
        "mr.",
        "mrs.",
        "ms.",
        "dr.",
        "st.",
        "no.",
        "approx.",
    }
)


_TOKEN_FIELDS = {"target_tokens", "min_tokens", "max_tokens", "overlap_tokens"}
_SENTENCE_FIELDS = {"sentences_per_passage", "stride", "max_passage_chars"}


class ChunkingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal["tokens", "sentences"] = "tokens"
    # "tokens" strategy: 200-400 token chunks with overlap.
    target_tokens: Annotated[int, Field(strict=True, ge=20, le=600)] = 300
    min_tokens: Annotated[int, Field(strict=True, ge=10, le=600)] = 200
    max_tokens: Annotated[int, Field(strict=True, ge=20, le=600)] = 400
    overlap_tokens: Annotated[int, Field(strict=True, ge=0, le=300)] = 50
    # "sentences" strategy.
    sentences_per_passage: Annotated[int, Field(strict=True, ge=1, le=10)] = 2
    stride: Annotated[int, Field(strict=True, ge=1, le=10)] = 1
    max_passage_chars: Annotated[int, Field(strict=True, ge=50, le=MAX_PASSAGE_CHARS)] = 1_000

    @model_validator(mode="after")
    def _check(self) -> ChunkingConfig:
        # Settings for the other strategy would be silently ignored, so they are refused.
        foreign = (
            _SENTENCE_FIELDS if self.strategy == "tokens" else _TOKEN_FIELDS
        ) & self.model_fields_set
        if foreign:
            raise ValueError(
                f"{', '.join(sorted(foreign))} do not apply to the {self.strategy!r} strategy"
            )
        if self.stride > self.sentences_per_passage:
            raise ValueError(
                "stride must not exceed sentences_per_passage, or text would be skipped"
            )
        if not self.min_tokens <= self.target_tokens <= self.max_tokens:
            raise ValueError("token sizes must satisfy min_tokens <= target_tokens <= max_tokens")
        if self.overlap_tokens >= self.min_tokens:
            raise ValueError("overlap_tokens must be smaller than min_tokens")
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


def _token_windows(text: str, start: int, end: int, max_tokens: int) -> list[tuple[int, int]]:
    """[start, end) cut into consecutive windows of at most ``max_tokens`` whitespace tokens."""
    words = [m.span() for m in _WORD_TOKEN.finditer(text, start, end)]
    return [
        (words[i][0], words[min(i + max_tokens, len(words)) - 1][1])
        for i in range(0, len(words), max_tokens)
    ]


def _token_spans(text: str, config: ChunkingConfig) -> list[tuple[int, int]]:
    """Chunk spans for the "tokens" strategy (see the module docstring)."""
    segments: list[tuple[int, int]] = []
    for para_start, para_end in _split_at(_PARAGRAPH_BREAK, text, 0, len(text)):
        for seg_start, seg_end in _segments(text, para_start, para_end, MAX_PASSAGE_CHARS):
            segments.extend(_token_windows(text, seg_start, seg_end, config.max_tokens))
    if not segments:
        return []
    tokens = [len(_WORD_TOKEN.findall(text, s, e)) for s, e in segments]

    def fits(first: int, last: int) -> bool:
        return segments[last][1] - segments[first][0] <= MAX_PASSAGE_CHARS

    windows: list[tuple[int, int]] = []
    first = 0
    while True:
        last, total = first, tokens[first]
        while (
            total < config.target_tokens
            and last + 1 < len(segments)
            and total + tokens[last + 1] <= config.max_tokens
            and fits(first, last + 1)
        ):
            last += 1
            total += tokens[last]
        windows.append((first, last))
        if last + 1 >= len(segments):
            break
        start, overlap = last + 1, 0
        while start - 1 > first and overlap < config.overlap_tokens:
            start -= 1
            overlap += tokens[start]
        first = start

    # Extend a short final chunk backwards, so a document's tail is not a fragment.
    first, last = windows[-1]
    total = sum(tokens[first : last + 1])
    while (
        first > 0
        and total < config.min_tokens
        and total + tokens[first - 1] <= config.max_tokens
        and fits(first - 1, last)
    ):
        first -= 1
        total += tokens[first]
    windows[-1] = (first, last)
    return [(segments[a][0], segments[b][1]) for a, b in windows]


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


def chunk_document(
    document: ReferenceDocument, config: ChunkingConfig, doc_order: int = 0
) -> list[DocumentPassage]:
    """All passages of one document, in document order, without duplicate spans."""
    text = document.text
    spans: list[tuple[int, int]] = _token_spans(text, config) if config.strategy == "tokens" else []
    for para_start, para_end in (
        _split_at(_PARAGRAPH_BREAK, text, 0, len(text)) if config.strategy == "sentences" else []
    ):
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
