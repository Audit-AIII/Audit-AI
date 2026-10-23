"""EVAL.md Phase 6: the regression registry (eval/regressions.json) stays executable: every bug
and every required category points at tests that exist."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = json.loads((ROOT / "eval" / "regressions.json").read_text(encoding="utf-8"))
REQUIRED = {"numeric_discrepancies", "negations", "dates_and_outdated_information", "unit_mismatches", "compound_claims",
            "conflicting_evidence", "missing_evidence", "prompt_injection", "citation_failures", "correction_traceability",
            "invalid_model_outputs", "retrieval_failures", "human_review_routing", "dataset_validation", "report_generation"}


def exists(reference: str) -> bool:
    path, _, name = reference.partition("::")
    file = ROOT / path
    return file.is_file() and re.search(rf"^def {re.escape(name)}\(", file.read_text(encoding="utf-8"), re.MULTILINE) is not None


def test_every_required_category_is_covered():
    assert set(REGISTRY["coverage"]) == REQUIRED
    assert all(REGISTRY["coverage"][c] for c in REQUIRED)


@pytest.mark.parametrize("reference", sorted({t for tests in REGISTRY["coverage"].values() for t in tests}))
def test_every_coverage_reference_is_a_real_test(reference):
    assert exists(reference), reference


@pytest.mark.parametrize("bug", REGISTRY["bugs"], ids=[b["id"] for b in REGISTRY["bugs"]])
def test_every_confirmed_bug_has_a_permanent_test(bug):
    assert set(bug) == {"id", "found", "phase", "category", "title", "symptom", "fix", "tests", "status"}
    assert re.fullmatch(r"REG-\d{3}", bug["id"]) and bug["status"] in {"fixed", "known"}
    assert bug["category"] in REQUIRED and bug["tests"]
    assert all(exists(t) for t in bug["tests"]), bug["tests"]


def test_bug_ids_are_unique_and_never_reused():
    ids = [b["id"] for b in REGISTRY["bugs"]]
    assert len(ids) == len(set(ids)) and ids == sorted(ids)
