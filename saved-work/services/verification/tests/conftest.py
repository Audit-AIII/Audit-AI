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
