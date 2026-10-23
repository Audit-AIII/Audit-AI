import copy
import json
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.fixture
def request_data() -> dict:
    return copy.deepcopy(load_example("verification_request.json"))


@pytest.fixture
def report_data() -> dict:
    return copy.deepcopy(load_example("verification_report.json"))


@pytest.fixture
def supported_result(report_data) -> dict:
    return report_data["results"][0]


@pytest.fixture
def contradicted_result(report_data) -> dict:
    return report_data["results"][1]


@pytest.fixture
def error_result() -> dict:
    return copy.deepcopy(load_example("claim_result_error.json"))


@pytest.fixture(autouse=True, scope="session")
def _eval_reports_in_a_temporary_folder(tmp_path_factory):
    """run_eval.py writes a timestamped report for every run (EVAL.md Phase 7); tests must never
    write into the real eval/reports/."""
    import os

    previous = os.environ.get("INKLOOM_EVAL_REPORTS_DIR")
    os.environ["INKLOOM_EVAL_REPORTS_DIR"] = str(tmp_path_factory.mktemp("eval-reports"))
    yield
    if previous is None:
        os.environ.pop("INKLOOM_EVAL_REPORTS_DIR", None)
    else:
        os.environ["INKLOOM_EVAL_REPORTS_DIR"] = previous
