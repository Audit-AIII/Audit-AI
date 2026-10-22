"""Retrieval measured on the evaluation sets, with the default 200-400 token chunks. These are
regression gates pinned to the values measured when the token chunker was introduced (EVAL.md)."""

from pathlib import Path

import pytest

from inkloom_verify.chunking import ChunkingConfig
from inkloom_verify.evaluation.runner import load_records, run
from inkloom_verify.retrieval import RetrievalConfig

DATA = Path(__file__).resolve().parents[1] / "eval" / "data"


def recall(dataset: str, top_k: int, strategy: str = "tokens", split: str = "all"):
    report = run(DATA / dataset, baseline="abstain", split=split,
                 retrieval=(ChunkingConfig(strategy=strategy), RetrievalConfig(top_k=top_k)))
    return report.results.retrieval.evidence_hit_rate


@pytest.mark.parametrize(
    ("dataset", "top_k", "numerator", "denominator"),
    [
        ("verification_v1.jsonl", 5, 36, 36),
        ("verification_v1.jsonl", 1, 35, 36),
        ("retrieval_v1.jsonl", 5, 32, 32),
        ("retrieval_v1.jsonl", 1, 32, 32),
    ],
)
def test_recall_does_not_regress(dataset, top_k, numerator, denominator):
    measured = recall(dataset, top_k)
    assert measured.denominator == denominator
    assert measured.numerator >= numerator


def test_retrieval_dataset_has_long_documents_and_gold_sentences():
    records = load_records(DATA / "retrieval_v1.jsonl")
    assert len(records) == 34
    handbook = records[0].references[0]
    assert len(handbook.text.split()) > 1000  # long enough that chunking matters
    assert all({d.doc_id for d in r.references} == {"product-handbook", "company-overview"} for r in records)
    assert sum(1 for r in records if r.gold_evidence) == 32
