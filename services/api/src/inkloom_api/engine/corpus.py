"""The approved reference corpus for one review: exactly the sources the engine is allowed to
cite. Split out of pipeline.py so evidence_validator.py (Phase 4) can depend on `CorpusEntry`
without a circular import.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from inkloom_verify.schemas import ReferenceDocument

from ..models import BrandSource, SourceVersion


@dataclass(frozen=True)
class CorpusEntry:
    brand_source_id: uuid.UUID
    source_version_id: uuid.UUID
    document: ReferenceDocument


def build_corpus(sources: list[tuple[BrandSource, SourceVersion]]) -> list[CorpusEntry]:
    """One `ReferenceDocument` per approved brand source, at its latest version. Callers must
    only pass sources already scoped to the right brand, organisation and `approved` status —
    this is what makes a citation outside this list rejectable as `unknown_source` rather than
    something this function re-checks (see evidence_validator.py)."""
    return [
        CorpusEntry(
            brand_source_id=brand_source.id,
            source_version_id=source_version.id,
            document=ReferenceDocument(
                doc_id=str(brand_source.id),
                version=str(source_version.version_number),
                title=brand_source.title,
                text=source_version.text,
                text_sha256=source_version.text_sha256,
            ),
        )
        for brand_source, source_version in sources
    ]


def corpus_lookup(corpus: list[CorpusEntry]) -> dict[tuple[str, str], CorpusEntry]:
    """Keyed by (doc_id, text_sha256), matching how a Citation identifies its source document."""
    return {(entry.document.doc_id, entry.document.text_sha256): entry for entry in corpus}
