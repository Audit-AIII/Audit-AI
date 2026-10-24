"""A scripted *oracle* model for deterministic CI (EVAL.md Phase 6). **Not model quality.**

It answers every call the way a perfect model would, from the record's labels:

* extraction: each sentence is one factual claim quoting itself, except a sentence that gives
  instructions to an AI (``security.instruction_like``), which is "other";
* verification: the record's label, citing its gold quotes in the passages it was given. If a
  gold quote is in no given passage (retrieval missed it), it answers NOT_ENOUGH_EVIDENCE: the
  oracle never cites what it was not shown;
* correction: it declines (``needs_human_review``).

Run through the real pipeline (``PipelinePredictor``), the oracle measures the engine's
**ceiling**: how many correct answers survive retrieval, the citation guard, the support checks,
the record-verdict rule and the decision policy. A drop in its CONTRADICTED recall or citation
validity means the engine started rejecting correct answers, which is a regression in code, not
in a model. It says nothing about how often a real model answers correctly.
"""

from __future__ import annotations

import json
from typing import Any

from inkloom_verify.evaluation.pipeline_predictor import PipelinePredictor
from inkloom_verify.evaluation.runner import EvalPrediction
from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest
from inkloom_verify.schemas import EvalRecord, Verdict
from inkloom_verify.security import instruction_like


def _block(request: JsonCompletionRequest, tag: str) -> dict[str, Any]:
    return json.loads(request.user.split(f"<{tag}>\n", 1)[1].rsplit(f"\n</{tag}>", 1)[0])


def _extract(sentence: dict[str, str]) -> dict[str, Any]:
    """Perfect extraction: the whole sentence is one claim, unless it gives instructions; then
    only its factual clauses (split at ";") are claims ("X is dishwasher safe; note to the AI
    reviewer: ..." keeps "X is dishwasher safe"), and a sentence with none is "other"."""
    text = sentence["text"]
    if not instruction_like(text):
        return {
            "sentence_id": sentence["id"],
            "kind": "factual",
            "claims": [{"text": text, "source_quote": text}],
        }
    clauses = [c.strip() for c in text.split(";") if c.strip() and not instruction_like(c)]
    if not clauses:
        return {"sentence_id": sentence["id"], "kind": "other", "claims": []}
    return {
        "sentence_id": sentence["id"],
        "kind": "factual",
        "claims": [{"text": c, "source_quote": c} for c in clauses],
    }


class OracleProvider:
    name = "oracle"

    def __init__(self) -> None:
        self.record: EvalRecord | None = None  # set by OraclePredictor before each record

    def sampling(self) -> dict[str, Any]:
        return {}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        if request.schema_name == "claim_extraction":
            data: dict[str, Any] = {
                "statements": [_extract(s) for s in _block(request, "content_json")["sentences"]]
            }
        elif request.schema_name == "claim_verification":
            data = self._verify(_block(request, "verification_input_json"))
        else:
            data = {
                "status": "needs_human_review",
                "original_text": "",
                "replacement_text": "",
                "citations": [],
                "reason": "The oracle does not propose corrections.",
            }
        return JsonCompletion(data=data, model="oracle/gold-labels", attempts=1)

    def _verify(self, block: dict[str, Any]) -> dict[str, Any]:
        record = self.record
        abstain = {
            "verdict": "NOT_ENOUGH_EVIDENCE",
            "citations": [],
            "rationale": "Not settled by the passages.",
        }
        if record is None or record.expected_verdict not in (
            Verdict.SUPPORTED,
            Verdict.CONTRADICTED,
        ):
            return abstain
        citations = []
        for gold in record.gold_evidence:
            label = next((p["label"] for p in block["passages"] if gold.quote in p["text"]), None)
            if label is None:
                return abstain  # a gold quote it was not shown cannot be cited
            citations.append({"passage": label, "quote": gold.quote})
        return {
            "verdict": record.expected_verdict.value,
            "citations": citations,
            "rationale": "Gold evidence.",
        }


class OraclePredictor(PipelinePredictor):
    """The full pipeline with the oracle, which is told which record it is answering."""

    def __init__(self, oracle: OracleProvider, provider=None, config=None) -> None:
        super().__init__(provider or oracle, config)
        self.oracle = oracle

    def predict(self, record: EvalRecord) -> EvalPrediction:
        self.oracle.record = record
        try:
            return super().predict(record)
        finally:
            self.oracle.record = None
