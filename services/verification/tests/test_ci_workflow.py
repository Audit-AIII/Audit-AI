"""EVAL.md Phase 6: the CI workflow runs the mandatory evaluation checks and keeps the live model
out of them. Text checks (no YAML library is a dependency); the YAML was also parsed with js-yaml
during review."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT.parents[1] / ".github" / "workflows" / "verification-engine.yml").read_text(
    encoding="utf-8"
)


def job(name: str) -> str:
    """The text of one job, up to the next top-level job."""
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", WORKFLOW, re.MULTILINE | re.DOTALL
    )
    assert match, name
    return match.group(1)


def test_the_four_stages_exist():
    for name in ("tests", "dataset", "evaluation", "model-evaluation"):
        job(name)


def test_mandatory_checks_run_on_every_push_and_pull_request():
    assert re.search(r"^  push:", WORKFLOW, re.MULTILINE) and re.search(
        r"^  pull_request:", WORKFLOW, re.MULTILINE
    )
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
    assert not re.search(
        r"sk-or-|sk-[A-Za-z0-9]{16,}|OPENROUTER_API_KEY:[ \t]*['\"]?[A-Za-z0-9]", stripped
    )


def test_every_file_the_workflow_runs_exists():
    for path in re.findall(r"(tests/test_[a-z0-9_]+\.py)", WORKFLOW) + [
        "eval/run_eval.py",
        "eval/dataset.jsonl",
        "constraints.txt",
    ]:
        assert (ROOT / path).is_file(), path


# --- Repository-wide integrity workflow (Fix Plan item 6) -----------------------------------------

REPO = ROOT.parents[1]
INTEGRITY = (REPO / ".github" / "workflows" / "repo-integrity.yml").read_text(encoding="utf-8")


def integrity_job(name: str) -> str:
    match = re.search(
        rf"^  {re.escape(name)}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", INTEGRITY, re.MULTILINE | re.DOTALL
    )
    assert match, name
    return match.group(1)


def test_integrity_checks_run_on_every_push_and_pull_request_for_any_path():
    assert re.search(r"^  push:\n", INTEGRITY, re.MULTILINE) and re.search(
        r"^  pull_request:\n", INTEGRITY, re.MULTILINE
    )
    assert (
        "paths:" not in INTEGRITY
    )  # a conflict marker or broken import can come from any directory
    assert "continue-on-error" not in INTEGRITY


def test_conflict_marker_step_fails_when_git_grep_finds_a_marker():
    step = integrity_job("conflict-markers")
    assert "if git grep -nE '^(<<<<<<<|>>>>>>>)'; then" in step
    assert "exit 1" in step


def test_backend_is_installed_compiled_and_imported_without_secrets():
    step = integrity_job("api-import")
    assert 'python -m pip install -e ".[dev]" -e ../verification -c constraints.txt' in step
    assert "python -m compileall -q src tests migrations scripts" in step
    assert "import inkloom_api.main" in step
    assert "secrets." not in INTEGRITY and "AUTH_SECRET_KEY" not in step.split("run:")[-1]
    assert (
        "DATABASE_URL: postgresql+psycopg://ci:ci@localhost:5432/ci-import-check-only" in step
    )  # placeholder only
    assert (REPO / "services" / "api" / "constraints.txt").is_file()


def test_the_repository_has_no_conflict_markers_now():
    """The same check, locally: any tracked file starting a line with <<<<<<< or >>>>>>>."""
    import subprocess

    found = subprocess.run(
        ["git", "-C", str(REPO), "grep", "-nE", "^(<<<<<<<|>>>>>>>)"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert found.returncode == 1 and found.stdout == "", found.stdout[:500]
