"""Can Member 1's review screen be filled from the actual POST /v1/verify response?

audit-ai-final/frontend/app/app/review/page.tsx renders hard-coded PROBLEMS today and calls no
API. These tests read the real JSON response the way a TypeScript client would (plain objects,
no engine models) and build every value that page shows. Severity and the row title are not
engine outputs: Member 3 assigns them (services/api engine/pipeline.py), so they are excluded.
"""

import json
import os
import warnings

from e2e_support import CONTENT, CONTRADICTED_CLAIM, RoutedProvider, careful_model, request
from inkloom_verify.pipeline import PipelineEngine

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

from inkloom_verify.api import create_verify_router, install_dev_error_handlers
from inkloom_verify.fake_engine import FakeEngine

CHIP = {"SUPPORTED": "matches", "CONTRADICTED": "contradicted", "NOT_ENOUGH_EVIDENCE": "unverified", "ERROR": "unverified"}


def post(engine, body: dict) -> dict:
    app = FastAPI()
    install_dev_error_handlers(app)
    app.include_router(create_verify_router(engine))
    response = TestClient(app).post("/v1/verify", json=body)
    assert response.status_code == 200
    return json.loads(response.text)  # plain JSON, as the browser receives it


def review_screen(body: dict, report: dict) -> dict:
    """The review page's values, built only from the request the client sent and the response."""
    content = body["content"]["text"]
    titles = {d["doc_id"]: d.get("title") for d in body["references"]}
    versions = {d["doc_id"]: d.get("version") for d in report["references"]}
    rows = []
    for r in report["results"]:
        claim, span = r["claim"], r["claim"]["source_span"]
        row = {
            "highlight": content[span["start"]:span["end"]],  # panel 01
            "chip": CHIP[r["verdict"]],  # panel 02
            "review": r["requires_human_review"],
            "quote": None, "source": None, "facts_say": None, "draft_says": None, "suggestion": None,
            "problem": r.get("model_rationale"),  # model-written: must be labelled as such
        }
        assert row["highlight"] == claim["text"]  # contract 0.2.0
        if r["citations"]:
            first = r["citations"][0]
            row["quote"] = first["quote"]  # panel 03
            row["source"] = (titles.get(first["doc_id"]), versions.get(first["doc_id"]))
        correction = r.get("correction")
        if correction:
            t = correction["target_span"]
            row["facts_say"], row["draft_says"] = correction["replacement_text"], correction["original_text"]
            row["suggestion"] = content[span["start"]:t["start"]] + correction["replacement_text"] + content[t["end"]:span["end"]]
        rows.append(row)
    coverage = report["score"]["evidence_coverage"]
    return {"rows": rows, "coverage": coverage["value"], "coverage_counts": (coverage["supported"], coverage["checked"])}


def test_every_value_of_the_review_screen_comes_from_the_live_engine_response():
    body = json.loads(request().model_dump_json())
    screen = review_screen(body, post(PipelineEngine(RoutedProvider(careful_model)), body))
    rows = {r["highlight"]: r for r in screen["rows"]}
    contradicted = rows[CONTRADICTED_CLAIM]
    assert contradicted["chip"] == "contradicted" and contradicted["review"] is True
    assert contradicted["quote"] == "Price: €129 (EU launch price)."
    assert contradicted["source"] == ("Lumen Pods Product Fact Sheet", "v2")
    assert (contradicted["facts_say"], contradicted["draft_says"]) == ("€129", "€99")
    assert contradicted["suggestion"] == "The Lumen Pods price is €129."
    assert screen["coverage_counts"] == (1, 3) and 0 < screen["coverage"] < 1


def test_unverified_and_failed_claims_never_look_contradicted_or_carry_evidence():
    body = json.loads(request().model_dump_json())
    screen = review_screen(body, post(PipelineEngine(RoutedProvider(careful_model)), body))
    for row in screen["rows"]:
        if row["chip"] == "unverified":
            assert row["quote"] is None and row["suggestion"] is None and row["review"] is True


def test_the_fake_engine_response_has_the_same_shape():
    body = json.loads(request(content=CONTENT).model_dump_json())
    report = post(FakeEngine(), body)
    screen = review_screen(body, report)
    assert screen["rows"] and {r["chip"] for r in screen["rows"]} <= set(CHIP.values())
    assert report["provenance"]["provider"] == "fake"  # labelled: never shown as a real check
    assert report["score"]["requires_human_review"] is True  # its request-level error keeps it from being review-free


def test_the_page_this_checks_still_has_the_expected_sections():
    page = os.path.join(os.path.dirname(__file__), *[".."] * 3, "audit-ai-final", "frontend", "app", "app", "review", "page.tsx")
    if not os.path.exists(page):
        return  # the frontend may be checked out separately
    text = open(page, encoding="utf-8").read()
    for marker in ("Your draft", "Problems found", "Why it was flagged", "evidence__quote", "Your facts say",
                   "Your draft says", "We suggest", "coverage__pct"):
        assert marker in text, marker
