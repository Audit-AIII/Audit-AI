"""Exports the engine's contracts as JSON Schema for integrators who do not use Python.

Run ``python -m inkloom_verify.json_schema`` from ``services/verification`` to regenerate
``schemas/``. A test fails when the committed files drift from the models.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from inkloom_verify.api_contract import Report as PublicReport
from inkloom_verify.api_contract import VerifyRequest as PublicVerifyRequest
from inkloom_verify.evaluation.summary import EvaluationSummary, IncompleteEvaluation, NoEvaluation
from inkloom_verify.schemas import (
    BrandRules,
    ClaimVerificationInput,
    ContentMetadata,
    EvalRecord,
    RuleEvaluation,
    VerificationReport,
    VerificationRequest,
)

EXPORTED_MODELS: dict[str, type[BaseModel]] = {
    "verification_request": VerificationRequest,
    "verification_report": VerificationReport,
    "claim_verification_input": ClaimVerificationInput,
    "eval_record": EvalRecord,
    "public_report": PublicReport,  # the public API contract (api_contract.py)
    "public_verify_request": PublicVerifyRequest,  # POST /v1/verify request body
    # GET /api/evaluations/latest (Trust Scorecard), contract evaluation-summary-v1: one of these three
    "evaluation_summary": EvaluationSummary,
    "evaluation_incomplete": IncompleteEvaluation,
    "evaluation_none": NoEvaluation,
    # The rules module (rules.evaluate_rules; RULES_HANDOFF.md): its input and its result
    "brand_rules": BrandRules,
    "content_metadata": ContentMetadata,
    "rule_evaluation": RuleEvaluation,
}

DEFAULT_OUT_DIR = Path(__file__).resolve().parents[2] / "schemas"


def render(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"


def export(out_dir: Path = DEFAULT_OUT_DIR) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in EXPORTED_MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(render(model), encoding="utf-8", newline="\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in export(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT_DIR):
        print(path)
