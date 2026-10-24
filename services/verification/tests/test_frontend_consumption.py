"""Can Member 1's review screen be filled from the actual POST /v1/verify response (public contract)?

audit-ai-final/frontend/app/app/review/page.tsx renders hard-coded PROBLEMS today and calls no
API. These tests read the real JSON response the way a TypeScript client would (plain objects,
no engine models) and build every value that page shows. Not from the engine: severity and the
row title (Member 3 assigns them), and the source document's title and version (the public
Evidence carries doc_id only; the frontend gets titles from the backend's sources API).
"""

import json
import os
import warnings

from e2e_support import CONTENT, CONTRADICTED_CLAIM, DOCS, RoutedProvider, careful_model

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

from inkloom_verify.api import create_verify_router, install_dev_error_handlers
from inkloom_verify.pipeline import PipelineEngine

CHIP = {
    "SUPPORTED": "matches",
    "CONTRADICTED": "contradicted",
    "NOT_ENOUGH_EVIDENCE": "unverified",
    "ERROR": "unverified",
}
BODY = {
    "request_id": "req_ui",
    "content": {"id": "draft-1", "text": CONTENT},
    "reference_set_id": "ref_pods",
}


def post(body: dict) -> tuple[int, dict]:
    app = FastAPI()
    install_dev_error_handlers(app)
    loader = (
        lambda tenant, ref: [DOCS["pods-fact-sheet"], DOCS["company-facts"]]
        if ref == "ref_pods"
        else None
    )  # noqa: E731
    app.include_router(
        create_verify_router(
            PipelineEngine(RoutedProvider(careful_model)),
            reference_set_loader=loader,
            authenticated_tenant=lambda: "tenant-ui",
        )
    )
    response = TestClient(app).post("/v1/verify", json=body)
    return response.status_code, json.loads(response.text)  # plain JSON, as the browser receives it


def review_screen(body: dict, report: dict) -> dict:
    """The review page's values, built only from the request the client sent and the response."""
    content = body["content"]["text"]
    rows = []
    for entry in report["claims"]:
        claim, verdict = entry["claim"], entry["verdict"]
        span = claim["span"]
        row = {
            "highlight": content[span["start"] : span["end"]],  # panel 01
            "chip": CHIP[verdict["status"]],  # panel 02
            "review": verdict["needs_human_review"],
            "quote": None,
            "source_doc": None,
            "facts_say": None,
            "draft_says": None,
            "suggestion": None,
        }
        assert row["highlight"] == claim["text"]
        if verdict["evidence"]:
            row["quote"] = verdict["evidence"][0]["quote"]  # panel 03
            row["source_doc"] = verdict["evidence"][0]["doc_id"]
        correction = verdict.get("correction")
        if correction and correction["status"] == "proposed":
            t = correction["span"]
            row["facts_say"], row["draft_says"] = (
                correction["replacement_text"],
                correction["original_text"],
            )
            row["suggestion"] = (
                content[span["start"] : t["start"]]
                + correction["replacement_text"]
                + content[t["end"] : span["end"]]
            )
        rows.append(row)
    checked = [e for e in report["claims"] if e["verdict"]["status"] != "ERROR"]
    supported = [e for e in checked if e["verdict"]["status"] == "SUPPORTED"]
    return {
        "rows": rows,
        "coverage": (len(supported), len(checked)),
    }  # the page's "backed by your documents"


def test_every_engine_value_of_the_review_screen_comes_from_the_response():
    status, report = post(BODY)
    assert status == 200
    screen = review_screen(BODY, report)
    rows = {r["highlight"]: r for r in screen["rows"]}
    contradicted = rows[CONTRADICTED_CLAIM]
    assert contradicted["chip"] == "contradicted" and contradicted["review"] is True
    assert (
        contradicted["quote"] == "Price: €129 (EU launch price)."
        and contradicted["source_doc"] == "pods-fact-sheet"
    )
    assert (contradicted["facts_say"], contradicted["draft_says"]) == ("€129", "€99")
    assert contradicted["suggestion"] == "The Lumen Pods price is €129."
    assert screen["coverage"] == (1, 3)


def test_unverified_and_failed_claims_never_look_contradicted_or_carry_evidence():
    _, report = post(BODY)
    for row in review_screen(BODY, report)["rows"]:
        if row["chip"] == "unverified":
            assert row["quote"] is None and row["suggestion"] is None and row["review"] is True


def test_the_frontend_still_renders_the_engine_derived_fields():
    """Since Member 1's commit 99de117 the review screen is live: ReviewResult.tsx renders Member 3's
    GET /api/reviews/{id} (FindingOut in lib/api/types.ts), not POST /v1/verify. These are the
    engine-derived values it shows; if they disappear, this mapping needs revisiting."""
    frontend = os.path.join(os.path.dirname(__file__), *[".."] * 3, "audit-ai-final", "frontend")
    component = os.path.join(frontend, "app", "app", "review", "ReviewResult.tsx")
    types = os.path.join(frontend, "lib", "api", "types.ts")
    if not (os.path.exists(component) and os.path.exists(types)):
        return  # the frontend may be checked out separately
    rendered = open(component, encoding="utf-8").read()
    for marker in (
        "Why it was flagged",
        "evidence__quote",
        "suggestionFor",
        "requires_human_review",
        "verification_status",
    ):
        assert marker in rendered, marker
    # Since Member 1's 53ef611 the suggestion wording lives in components/app/reviewLabels.ts. The
    # evidence-backed correction and the engine's safer wording must stay apart there: only the
    # correction may be presented as backed by the brand's documents (contract 2026-10-24).
    labels = open(
        os.path.join(frontend, "components", "app", "reviewLabels.ts"), encoding="utf-8"
    ).read()
    suggestion = labels.split("export function suggestionFor", 1)[1].split("\n}\n", 1)[0]
    assert "suggested_correction" in suggestion and "safer_wording" in suggestion
    assert "We suggest (backed by your documents)" in suggestion
    assert 'SAFER_WORDING_LABEL = "Safer wording, not evidence-backed"' in labels
    assert "label: SAFER_WORDING_LABEL, evidenceBacked: false" in suggestion
    finding = (
        open(types, encoding="utf-8").read().split("export type FindingOut", 1)[1].split("};", 1)[0]
    )
    for field in (
        "span",
        "verification_status",
        "suggested_correction",
        "requires_human_review",
        "evidence",
    ):
        assert f"{field}:" in finding, field
