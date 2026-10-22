"""Shared fixtures for the end-to-end tests: documented reference documents and a scripted model.

The scripted model stands in for an LLM so the workflow can be tested deterministically. It
answers like a careful model would for the claims it knows. It is not evidence of how a real
model behaves.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.providers.base import JsonCompletion, JsonCompletionRequest, ProviderTimeoutError
from inkloom_verify.schemas import ReferenceDocument, VerificationRequest

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "eval" / "data" / "verification_v1.jsonl"
E2E = ROOT / "examples" / "end_to_end"


def dataset_documents() -> dict[str, ReferenceDocument]:
    """The reference documents shipped with evaluation dataset v1 (EVAL.md, dataset card)."""
    return {d.doc_id: d for r in load_records(DATASET) for d in r.references}


DOCS = dataset_documents()

SUPPORTED_CLAIM = "Lumen Pods offer up to 12 hours of playback per charge."
CONTRADICTED_CLAIM = "The Lumen Pods price is €99."
UNVERIFIED_CLAIM = "Lumen Pods have active noise cancellation."
ERROR_CLAIM = "Lumen Goods was founded in 2019 in Lisbon."
OPINION = "We think they sound amazing."
CONTENT = " ".join([SUPPORTED_CLAIM, CONTRADICTED_CLAIM, UNVERIFIED_CLAIM, ERROR_CLAIM, OPINION])

# claim text -> (verdict, quote that decides it)
VERDICTS = {
    SUPPORTED_CLAIM: ("SUPPORTED", "up to 12 hours of playback per charge"),
    CONTRADICTED_CLAIM: ("CONTRADICTED", "Price: €129 (EU launch price)."),
    "The Lumen Pods price is €129.": ("SUPPORTED", "Price: €129 (EU launch price)."),  # the re-check
    UNVERIFIED_CLAIM: ("NOT_ENOUGH_EVIDENCE", None),
}


def request(content: str = CONTENT, tenant: str = "tenant-demo", doc_ids=("pods-fact-sheet", "company-facts"),
            request_id: str = "req-e2e-0001") -> VerificationRequest:
    return VerificationRequest(
        request_id=request_id, tenant_id=tenant, content={"content_id": "draft-e2e", "text": content},
        references=[DOCS[d] for d in doc_ids],
    )


def data_block(request: JsonCompletionRequest, tag: str) -> dict:
    return json.loads(request.user.split(f"<{tag}>\n", 1)[1].rsplit(f"\n</{tag}>", 1)[0])


def careful_model(request: JsonCompletionRequest) -> dict[str, Any] | Exception:
    if request.schema_name == "claim_extraction":
        statements = []
        for s in data_block(request, "content_json")["sentences"]:
            if s["text"].startswith("We think"):
                statements.append({"sentence_id": s["id"], "kind": "opinion", "claims": []})
            else:
                statements.append({"sentence_id": s["id"], "kind": "factual",
                                   "claims": [{"text": s["text"], "source_quote": s["text"]}]})
        return {"statements": statements}
    if request.schema_name == "claim_verification":
        block = data_block(request, "verification_input_json")
        if block["claim"] == ERROR_CLAIM:
            return ProviderTimeoutError("scripted/model did not answer within 30s")
        verdict, quote = VERDICTS.get(block["claim"], ("NOT_ENOUGH_EVIDENCE", None))
        citations = []
        label = next((p["label"] for p in block["passages"] if quote and quote in p["text"]), None)
        if label is None:  # the deciding passage was not retrieved: a careful model cannot cite it
            verdict = "NOT_ENOUGH_EVIDENCE"
        elif quote:
            citations = [{"passage": label, "quote": quote}]
        return {"verdict": verdict, "citations": citations, "rationale": f"Decided from {len(citations)} passage(s)."}
    if request.schema_name == "claim_correction":
        return {"status": "corrected", "original_text": "€99", "replacement_text": "€129",
                "citations": ["C1"], "reason": "C1 gives the price."}
    raise AssertionError(f"unexpected schema {request.schema_name}")


class RoutedProvider:
    """A provider whose every call is answered by ``respond``; records each request."""

    name = "scripted"

    def __init__(self, respond: Callable[[JsonCompletionRequest], Any], model: str = "scripted/careful-v1") -> None:
        self.respond = respond
        self.model = model
        self.calls: list[JsonCompletionRequest] = []

    def sampling(self) -> dict[str, Any]:
        return {"temperature": 0.0, "seed": 0}

    def complete_json(self, request: JsonCompletionRequest) -> JsonCompletion:
        self.calls.append(request)
        reply = self.respond(request)
        if isinstance(reply, Exception):
            raise reply
        return JsonCompletion(data=reply, model=self.model, attempts=1)
