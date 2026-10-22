"""Evidence retrieval: finds the reference passages most relevant to one claim.

Retrieval is lexical and deterministic. It never calls a model, never rewrites text, and only
returns passages that are exact slices of the documents it was given. Document text is treated
as inert data: it is tokenised and counted, never interpreted, followed or executed.

The ``EvidenceRetriever`` protocol is the seam for replacing the method later (dense or hybrid
retrieval); callers depend on it, not on BM25.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from rank_bm25 import BM25Okapi

from inkloom_verify.chunking import ChunkingConfig, DocumentPassage, chunk_document
from inkloom_verify.schemas import (
    MAX_PASSAGES_PER_CLAIM,
    Claim,
    EvidencePassage,
    ReferenceDocument,
    RetrievalMethod,
    RetrievalProvenance,
)

# Upper bound on passages indexed per corpus; MAX_TOTAL_REFERENCE_CHARS of short sentences
# stays well below it. Exceeding it means the corpus is not what the engine was sized for.
MAX_INDEXED_PASSAGES = 50_000

_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")
# Function words that carry no evidence on their own. Deliberately small: words like "not",
# "no", "only" and "never" are kept because they change what a claim means.
_STOPWORDS = frozenset(
    """a an and are as at be been being but by can could did do does for from had has have he her
    his i if in into is it its may might of on or our she should so than that the their them then
    there these they this those to was we were what when where which who will with would you your""".split()
)


class RetrievalError(ValueError):
    """The retrieval input cannot be used as given."""


class RetrievalLimitError(RetrievalError):
    """The corpus exceeds what the retriever is sized for."""


class RetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    top_k: Annotated[int, Field(strict=True, ge=1, le=MAX_PASSAGES_PER_CLAIM)] = 5
    # BM25 parameters (standard defaults).
    k1: Annotated[float, Field(gt=0, le=3, allow_inf_nan=False)] = 1.5
    b: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.75
    # Relevance gate, applied before ranking: a passage must share at least this many distinct
    # query terms with the claim, and at least this fraction of them.
    min_matched_terms: Annotated[int, Field(strict=True, ge=1)] = 1
    min_term_coverage: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] = 0.25
    # Skip a candidate that overlaps a passage already selected from the same document. Off by
    # default: with overlapping windows (stride < sentences_per_passage) it can drop the window
    # that holds the evidence because a neighbouring window ranked higher.
    suppress_overlaps: bool = False


def tokenize(text: str) -> list[str]:
    """Lower-cased word and number tokens without stopwords. Numbers drop thousands separators."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    tokens = (token.replace(",", "") for token in _TOKEN.findall(normalized))
    return [token for token in tokens if token not in _STOPWORDS]


def _dedupe_key(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class _NonNegativeBM25(BM25Okapi):
    """BM25Okapi with the Lucene IDF, ``log(1 + (N - n + 0.5) / (n + 0.5))``.

    rank_bm25's Okapi IDF floors common terms at ``epsilon * average_idf``, which is negative
    for small corpora (a single passage gives every term a negative IDF), so a relevant passage
    can score below an irrelevant one. The Lucene IDF is always positive, so a passage that
    shares no term with the query scores exactly 0 and any shared term scores above 0.
    """

    def _calc_idf(self, nd: Mapping[str, int]) -> None:
        for word, freq in nd.items():
            self.idf[word] = math.log(1 + (self.corpus_size - freq + 0.5) / (freq + 0.5))
        self.average_idf = sum(self.idf.values()) / len(self.idf) if self.idf else 0.0


class EvidenceRetriever(Protocol):
    """Finds evidence for one claim within one fixed corpus of reference documents."""

    method: RetrievalMethod

    def retrieve(self, claim: Claim | Mapping[str, Any], top_k: int | None = None) -> list[EvidencePassage]:
        """Passages ranked best first; empty when nothing in the corpus is relevant."""
        ...


def _as_documents(documents: Iterable[ReferenceDocument | Mapping[str, Any]]) -> list[ReferenceDocument]:
    if isinstance(documents, (str, bytes, Mapping)):
        raise RetrievalError("documents must be a sequence of reference documents")
    validated = [d if isinstance(d, ReferenceDocument) else ReferenceDocument.model_validate(d) for d in documents]
    seen: set[str] = set()
    for document in validated:
        if document.doc_id in seen:
            raise RetrievalError(f"duplicate reference doc_id: {document.doc_id}")
        seen.add(document.doc_id)
    return validated


class BM25Retriever:
    """Lexical retrieval over the passages of one request's reference documents.

    Build one retriever per request (or per tenant corpus). It holds only the documents it
    was given, so evidence can never come from another tenant's documents.
    """

    method = RetrievalMethod.BM25

    def __init__(
        self,
        documents: Sequence[ReferenceDocument | Mapping[str, Any]],
        chunking: ChunkingConfig | None = None,
        config: RetrievalConfig | None = None,
    ) -> None:
        self.chunking = chunking or ChunkingConfig()
        self.config = config or RetrievalConfig()
        self.documents = _as_documents(documents)

        passages: list[DocumentPassage] = []
        for order, document in enumerate(self.documents):
            passages.extend(chunk_document(document, self.chunking, doc_order=order))
            if len(passages) > MAX_INDEXED_PASSAGES:
                raise RetrievalLimitError(f"reference documents produce more than {MAX_INDEXED_PASSAGES} passages")

        tokenized = [(passage, tokenize(passage.text)) for passage in passages]
        # A passage with no searchable terms (only punctuation or stopwords) can never match.
        indexed = [(passage, tokens) for passage, tokens in tokenized if tokens]
        self.passages: list[DocumentPassage] = [passage for passage, _ in indexed]
        self._terms: list[frozenset[str]] = [frozenset(tokens) for _, tokens in indexed]
        self._bm25 = (
            _NonNegativeBM25([tokens for _, tokens in indexed], k1=self.config.k1, b=self.config.b)
            if indexed
            else None
        )

    def retrieve(self, claim: Claim | Mapping[str, Any], top_k: int | None = None) -> list[EvidencePassage]:
        claim = claim if isinstance(claim, Claim) else Claim.model_validate(claim)
        limit = self.config.top_k if top_k is None else top_k
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_PASSAGES_PER_CLAIM:
            raise RetrievalError(f"top_k must be an integer from 1 to {MAX_PASSAGES_PER_CLAIM}")

        query = sorted(set(tokenize(claim.text)))
        if self._bm25 is None or not query:
            return []

        scores = self._bm25.get_scores(query)
        candidates = [i for i in range(len(self.passages)) if scores[i] > 0 and self._is_relevant(i, query)]
        # Best score first; ties go to the earlier document, then the earlier position.
        candidates.sort(key=lambda i: (-scores[i], self.passages[i].doc_order, self.passages[i].span.start))
        return [
            self._to_evidence(self.passages[i], float(scores[i]), rank)
            for rank, i in enumerate(self._select(candidates, limit), start=1)
        ]

    def _is_relevant(self, index: int, query: list[str]) -> bool:
        matched = sum(1 for term in query if term in self._terms[index])
        return matched >= self.config.min_matched_terms and matched / len(query) >= self.config.min_term_coverage

    def _select(self, candidates: list[int], limit: int) -> list[int]:
        """Takes candidates in rank order, skipping repeated text and overlapping windows."""
        selected: list[int] = []
        seen_text: set[str] = set()
        for index in candidates:
            passage = self.passages[index]
            key = _dedupe_key(passage.text)
            if key in seen_text:
                continue
            if self.config.suppress_overlaps and any(self._overlaps(passage, self.passages[s]) for s in selected):
                continue
            seen_text.add(key)
            selected.append(index)
            if len(selected) == limit:
                break
        return selected

    @staticmethod
    def _overlaps(a: DocumentPassage, b: DocumentPassage) -> bool:
        return a.doc_id == b.doc_id and a.span.start < b.span.end and b.span.start < a.span.end

    def _to_evidence(self, passage: DocumentPassage, score: float, rank: int) -> EvidencePassage:
        return EvidencePassage(
            passage_id=passage.passage_id,
            doc_id=passage.doc_id,
            doc_text_sha256=passage.doc_text_sha256,
            span=passage.span,
            text=passage.text,
            retrieval=RetrievalProvenance(method=self.method, score=round(score, 6), rank=rank),
        )
