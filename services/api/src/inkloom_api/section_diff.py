"""Phase 7 task 4: section-level hashing for the automatic source-version diff.

"Section" means exactly what `BM25Retriever` already chunks a document into — the default
`ChunkingConfig()` (strategy `"tokens"`, ~200-400 token windows), the same config my pipeline
uses when building the retriever (`engine/pipeline.py`). Reusing Member 2's `chunking.py`
read-only (no edits to their code) guarantees a "section" here is the same unit of text their
evidence passages already are, so "did the cited section change" is asking exactly the right
question rather than an approximation of it.
"""

from __future__ import annotations

import hashlib

from inkloom_verify.chunking import ChunkingConfig, chunk_document
from inkloom_verify.schemas import ReferenceDocument, SourceSpan

_CONFIG = ChunkingConfig()  # tokens strategy, matching engine/pipeline.py's BM25Retriever default


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_section_hashes(document: ReferenceDocument) -> list[str]:
    """Every section of this document, hashed. Stored on `source_versions.section_hashes` at
    creation time, and diffed against on the next version's upload."""
    return [_hash(passage.text) for passage in chunk_document(document, _CONFIG)]


def section_hash_for_span(document: ReferenceDocument, span: SourceSpan) -> str | None:
    """Which section a citation's `quote_span` falls inside, hashed - or `None` if no single
    section contains it (shouldn't normally happen; a citation's span always comes from a
    passage that itself came from chunking the same document the same way)."""
    for passage in chunk_document(document, _CONFIG):
        if passage.span.contains(span):
            return _hash(passage.text)
    return None
