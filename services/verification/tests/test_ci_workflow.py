"""EVAL.md Phase 6: the CI workflow runs the mandatory evaluation checks and keeps the live model
out of them. Text checks (no YAML library is a dependency); the YAML was also parsed with js-yaml
during review."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT.parents[1] / ".github" / "workflows" / "verification-engine.yml").read_text(encoding="utf-8")


def job(name: str) -> str:
    """The text of one job, up to the next top-level job."""
    match = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", WORKFLOW, re.MULTILINE | re.DOTALL)
    assert match, name
    return match.group(1)


def test_the_four_stages_exist():
    for name in ("tests", "dataset", "evaluation", "model-evaluation"):
        job(name)


def test_mandatory_checks_run_on_every_push_and_pull_request():
    assert re.search(r"^  push:", WORKFLOW, re.MULTILINE) and re.search(r"^  pull_request:", WORKFLOW, re.MULTILINE)
    assert "python -m pytest -q\n" in job("tests")
    assert "python -m inkloom_verify.evaluation.dataset eval/dataset.jsonl" in job("dataset")
    evaluation = job("evaluation")
    assert "python eval/run_eval.py --verdicts oracle --check-baseline" in evaluation
    assert "python eval/run_eval.py --check-baseline" in evaluation
    assert "continue-on-error" not in WORKFLOW  # a failing gate fails the job


def test_the_live_model_never_runs_in_mandatory_ci():
    live = job("model-evaluation")
    assert "if: github.event_name == 'workflow_dispatch' && inputs.run_model_evaluation" in live
    assert "environment: model-evaluation" in live
    assert "${{ secrets.OPENROUTER_API_KEY }}" in live
    for name in ("tests", "dataset", "evaluation"):
        assert "secrets." not in job(name) and "--verdicts openrouter" not in job(name)


def test_no_credential_is_written_in_the_workflow():
    # The only value OPENROUTER_API_KEY may have is the secret reference; nothing else on that line.
    stripped = WORKFLOW.replace("${{ secrets.OPENROUTER_API_KEY }}", "")
    assert not re.search(r"sk-or-|sk-[A-Za-z0-9]{16,}|OPENROUTER_API_KEY:[ \t]*['\"]?[A-Za-z0-9]", stripped)


def test_every_file_the_workflow_runs_exists():
    for path in re.findall(r"(tests/test_[a-z0-9_]+\.py)", WORKFLOW) + ["eval/run_eval.py", "eval/dataset.jsonl", "constraints.txt"]:
        assert (ROOT / path).is_file(), path
