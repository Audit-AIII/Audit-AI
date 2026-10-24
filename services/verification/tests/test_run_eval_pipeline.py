"""EVAL.md Phase 3: run_eval.py drives the real pipeline (verify_request) per record.

The model is a scripted provider, recorded to a cassette with --record (through the same code path
as a live run) and replayed offline with --replay. No test calls a real model, and a scripted run
is never reported as model quality."""

import importlib.util
import json
from pathlib import Path

import pytest

from e2e_support import data_block
from inkloom_verify.evaluation.pipeline_predictor import aggregate
from inkloom_verify.evaluation.replay import CASSETTE_KIND, RecordingProvider, ReplayProvider
from inkloom_verify.providers.base import JsonCompletion, MalformedOutputError, ProviderTimeoutError
from inkloom_verify.schemas import Verdict

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_eval_p3", ROOT / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_eval)
RECORDS = [
    json.loads(l)
    for l in (ROOT / "eval" / "dataset.jsonl").read_text(encoding="utf-8").splitlines()
    if l.strip()
]


def scripted(call, fail_on: dict[str, Exception] | None = None, opinion: set[str] = frozenset()):
    """A deterministic stand-in model. Extraction: every sentence is one claim (except sentences
    in ``opinion``). Verification: CONTRADICTED citing the price line for claims mentioning €99,
    otherwise NOT_ENOUGH_EVIDENCE. Correction: €99 -> €129 citing C1. ``fail_on`` raises the given
    error for verification of claims containing a key."""
    if call.schema_name == "claim_extraction":
        return {
            "statements": [
                {
                    "sentence_id": s["id"],
                    "kind": "opinion" if s["text"] in opinion else "factual",
                    "claims": []
                    if s["text"] in opinion
                    else [{"text": s["text"], "source_quote": s["text"]}],
                }
                for s in data_block(call, "content_json")["sentences"]
            ]
        }
    if call.schema_name == "claim_verification":
        block = data_block(call, "verification_input_json")
        for key, error in (fail_on or {}).items():
            if key in block["claim"]:
                raise error
        quote = "Price: €129 (EU launch price)."
        label = next((p["label"] for p in block["passages"] if quote in p["text"]), None)
        if "€99" in block["claim"] and label:
            return {
                "verdict": "CONTRADICTED",
                "citations": [{"passage": label, "quote": quote}],
                "rationale": "P1 gives €129.",
            }
        return {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "Not settled."}
    return {
        "status": "corrected",
        "original_text": "€99",
        "replacement_text": "€129",
        "citations": ["C1"],
        "reason": "Per C1.",
    }


class ScriptedProvider:
    name = "scripted"

    def __init__(self, **options):
        self.options = options

    def sampling(self):
        return {}

    def complete_json(self, request):
        return JsonCompletion(
            data=scripted(request, **self.options), model="scripted/model-1", attempts=1
        )


def live(monkeypatch, **options):
    """Makes --verdicts openrouter build the scripted provider instead of calling OpenRouter."""
    from inkloom_verify.providers import openrouter

    monkeypatch.setattr(
        openrouter.OpenRouterProvider,
        "from_env",
        classmethod(lambda cls, env=None: ScriptedProvider(**options)),
    )


def read(out: Path):
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    cases = (
        [json.loads(l) for l in (out / "cases.jsonl").read_text(encoding="utf-8").splitlines()]
        if (out / "cases.jsonl").exists()
        else []
    )
    return report, {c["record_id"]: c for c in cases}


@pytest.fixture(scope="module")
def cassette(tmp_path_factory):
    """One recorded scripted run: the cassette and the recording run's outputs."""
    out = tmp_path_factory.mktemp("record")
    mp = pytest.MonkeyPatch()
    live(mp)
    try:
        code = run_eval.main(
            ["--verdicts", "openrouter", "--record", str(out / "cassette.jsonl"), "--out", str(out)]
        )
    finally:
        mp.undo()
    return code, out


# --- Successful execution -----------------------------------------------------------------------------


def test_a_recorded_run_executes_the_real_pipeline_for_every_record(cassette):
    code, out = cassette
    report, cases = read(out)
    assert code == 0 and report["run"]["pipeline"] == "full"
    assert len(cases) == len(RECORDS) == report["verdicts"]["examples"] == 80
    v1_027 = cases["v1-027"]  # "Lumen Pods cost €99."
    assert v1_027["predicted"] == "CONTRADICTED" and v1_027["outcome"] == "correct"
    [claim] = v1_027["claims"]
    assert claim["citations"][0]["quote"] == "Price: €129 (EU launch price)."
    assert claim["evidence"] and claim["evidence"][0]["rank"] == 1  # retrieved passages are kept
    assert claim["requires_human_review"] is True  # CONTRADICTED always goes to a person
    assert claim["correction"]["status"] in {"proposed", "needs_human_review"}  # the corrector ran
    assert (
        cases["v1-001"]["predicted"] == "NOT_ENOUGH_EVIDENCE"
        and cases["v1-001"]["claims"][0]["citations"] == []
    )


def test_the_report_records_what_is_needed_to_reproduce_it(cassette):
    _, out = cassette
    run = read(out)[0]["run"]
    assert (
        run["dataset"]["sha256"] == run_eval.sha256(ROOT / "eval" / "dataset.jsonl")
        and run["dataset"]["locked"]
    )
    assert run["prompt_versions"] == run_eval.PROMPT_SETS["v1"]
    assert run["model_configuration"] == {"provider": "scripted"}
    assert run["retrieval_parameters"]["retrieval"]["top_k"] == 5
    assert (
        run["decision_policy"]["conflict_topic_overlap"] == 0.5
        and "review_rule" in run["decision_policy"]
    )
    assert run["created_at"] and run["verdict_source"] == "openrouter"


def test_a_scripted_model_is_never_reported_as_model_quality_when_replayed(cassette, tmp_path):
    _, out = cassette
    assert run_eval.main(["--replay", str(out / "cassette.jsonl"), "--out", str(tmp_path)]) == 0
    report, _ = read(tmp_path)
    assert (
        report["run"]["verdict_source"] == "replay"
        and report["run"]["replay"]["source"] == "scripted"
    )
    assert report["verdicts"]["is_model_quality"] is False


def test_replay_is_offline_and_reproduces_the_recorded_run_exactly(cassette, tmp_path):
    _, out = cassette
    recorded_report, recorded = read(out)
    first, second = tmp_path / "a", tmp_path / "b"
    for target in (first, second):
        assert run_eval.main(["--replay", str(out / "cassette.jsonl"), "--out", str(target)]) == 0
    (ra, ca), (rb, cb) = read(first), read(second)
    strip = lambda cases: {k: {**v, "seconds": 0} for k, v in cases.items()}  # noqa: E731
    assert strip(ca) == strip(cb) == strip(recorded)
    assert ra["verdicts"] == rb["verdicts"] and ra["cases"]["replay_misses"] == 0
    same = lambda v: {k: x for k, x in v.items() if k != "source"}  # noqa: E731 - "replay" vs "openrouter"
    assert same(ra["verdicts"]) == same(recorded_report["verdicts"])
    assert (
        recorded_report["verdicts"]["is_model_quality"] is False
    )  # the recording came from a scripted model


def test_the_cassette_holds_replies_never_credentials(cassette, monkeypatch):
    _, out = cassette
    lines = (out / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["kind"] == CASSETTE_KIND and all(
        "key" in json.loads(l) for l in lines[1:]
    )
    import httpx

    from inkloom_verify.providers.openrouter import OpenRouterProvider, OpenRouterSettings

    secret = "sk-or-v1-PHASE3-TEST-ONLY-NOT-A-REAL-KEY-0000"
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            json={
                "model": "a/b",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": "x"}'
                        },
                    }
                ],
            },
        )
    )
    path = out / "secret-check.jsonl"
    recorder = RecordingProvider(
        OpenRouterProvider(
            OpenRouterSettings(api_key=secret, models=["a/b"]),
            client=httpx.Client(transport=transport),
        ),
        path,
    )
    from inkloom_verify.providers.base import JsonCompletionRequest

    recorder.complete_json(
        JsonCompletionRequest(
            system="s", user="u", schema_name="claim_verification", json_schema={}
        )
    )
    assert secret not in path.read_text(encoding="utf-8")


# --- Pipeline failures and skipped records ----------------------------------------------------------


def test_provider_errors_become_error_cases_and_are_replayed_as_errors(tmp_path, monkeypatch):
    live(
        monkeypatch,
        fail_on={"5.3 g": ProviderTimeoutError("slow"), "340 kg": MalformedOutputError("bad")},
    )
    assert (
        run_eval.main(
            [
                "--verdicts",
                "openrouter",
                "--record",
                str(tmp_path / "c.jsonl"),
                "--out",
                str(tmp_path / "rec"),
            ]
        )
        == 0
    )
    monkeypatch.undo()
    assert (
        run_eval.main(["--replay", str(tmp_path / "c.jsonl"), "--out", str(tmp_path / "rep")]) == 0
    )
    for folder in ("rec", "rep"):
        report, cases = read(tmp_path / folder)
        assert (
            cases["v3-006"]["predicted"] == "ERROR"
            and cases["v3-006"]["reason"] == "claim error: PROVIDER_TIMEOUT"
        )
        assert (
            cases["v3-010"]["predicted"] == "ERROR"
            and cases["v3-010"]["reason"] == "claim error: MALFORMED_MODEL_OUTPUT"
        )
        assert report["verdicts"]["error_rate"]["numerator"] >= 2  # counted, not dropped


def test_a_record_with_no_extracted_claim_is_reported_as_skipped_not_dropped(tmp_path, monkeypatch):
    live(monkeypatch, opinion={"Lumen Pods charge over USB-C."})
    assert run_eval.main(["--verdicts", "openrouter", "--out", str(tmp_path)]) == 0
    report, cases = read(tmp_path)
    skipped = cases["v1-003"]
    assert (
        skipped["outcome"] == "skipped"
        and skipped["reason"] == "no_claim_extracted"
        and skipped["predicted"] == "ERROR"
    )
    assert (
        skipped["requires_human_review"] is True
        and report["cases"]["reasons"]["no_claim_extracted"] == 1
    )
    assert report["verdicts"]["examples"] == 80


def test_an_unexpected_pipeline_exception_is_an_error_case(tmp_path, monkeypatch):
    from inkloom_verify.evaluation import pipeline_predictor

    real = pipeline_predictor.verify_request

    def flaky(request, provider, config=None):
        if request.request_id == "eval-v1-001":
            raise RuntimeError("boom")
        return real(request, provider, config)

    live(monkeypatch)
    monkeypatch.setattr(pipeline_predictor, "verify_request", flaky)
    assert run_eval.main(["--verdicts", "openrouter", "--out", str(tmp_path)]) == 0
    _, cases = read(tmp_path)
    assert (
        cases["v1-001"]["outcome"] == "error"
        and cases["v1-001"]["reason"] == "pipeline raised RuntimeError"
    )


def test_a_replay_with_no_recordings_fails_the_evaluation_with_exit_3(tmp_path, capsys):
    empty = tmp_path / "empty.jsonl"
    empty.write_text(
        json.dumps({"kind": CASSETTE_KIND, "version": 1, "source": "scripted"}) + "\n",
        encoding="utf-8",
    )
    assert run_eval.main(["--replay", str(empty), "--out", str(tmp_path / "out")]) == 3
    report, cases = read(tmp_path / "out")
    assert report["run"]["evaluation_failed"] is True and report["cases"]["replay_misses"] > 0
    assert {c["outcome"] for c in cases.values()} == {
        "error"
    }  # every miss is reported, nothing is invented
    text = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "**Outcome: FAILED.**" in text and "no record received a verdict" in text
    assert "no record received a verdict" in capsys.readouterr().err


def test_a_partial_replay_reports_its_misses(cassette, tmp_path):
    _, out = cassette
    lines = (out / "cassette.jsonl").read_text(encoding="utf-8").splitlines()
    partial = tmp_path / "partial.jsonl"
    partial.write_text("\n".join(lines[: len(lines) // 2]) + "\n", encoding="utf-8")
    assert run_eval.main(["--replay", str(partial), "--out", str(tmp_path / "out")]) == 0
    report, cases = read(tmp_path / "out")
    assert report["cases"]["replay_misses"] > 0 and any(
        c["outcome"] == "error" for c in cases.values()
    )


# --- Invalid inputs -------------------------------------------------------------------------------------


def write_dataset(tmp_path, lines) -> Path:
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["{not json"], "not valid JSON"),
        ([json.dumps(RECORDS[0], ensure_ascii=False)] * 2, "duplicate record_id"),
        (
            [json.dumps({**RECORDS[0], "expected_verdict": "FALSE"}, ensure_ascii=False)],
            "expected_verdict",
        ),
    ],
    ids=["malformed", "duplicate", "bad-status"],
)
def test_an_invalid_dataset_stops_the_run_with_exit_2(tmp_path, capsys, lines, message):
    assert (
        run_eval.main(
            ["--dataset", str(write_dataset(tmp_path, lines)), "--out", str(tmp_path / "out")]
        )
        == 2
    )
    err = capsys.readouterr().err
    assert "invalid dataset" in err and message in err
    assert not (tmp_path / "out" / "report.json").exists()


def test_a_corrupt_cassette_stops_the_run_with_exit_2(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not a cassette\n", encoding="utf-8")
    assert run_eval.main(["--replay", str(bad), "--out", str(tmp_path / "out")]) == 2
    assert "cassette" in capsys.readouterr().err


def test_a_custom_dataset_runs_but_is_marked_unlocked(tmp_path, monkeypatch):
    live(monkeypatch)
    path = write_dataset(tmp_path, [json.dumps(r, ensure_ascii=False) for r in RECORDS[:3]])
    assert (
        run_eval.main(
            ["--verdicts", "openrouter", "--dataset", str(path), "--out", str(tmp_path / "out")]
        )
        == 0
    )
    report, cases = read(tmp_path / "out")
    assert report["run"]["dataset"]["locked"] is False and len(cases) == 3
    assert "not the locked dataset" in (tmp_path / "out" / "report.md").read_text(encoding="utf-8")


def test_record_needs_the_live_source(capsys):
    with pytest.raises(SystemExit):
        run_eval.main(["--record", "x.jsonl"])
    assert "--record needs --verdicts openrouter" in capsys.readouterr().err


# --- The record verdict rule ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ([Verdict.SUPPORTED, Verdict.CONTRADICTED], Verdict.CONTRADICTED),
        ([Verdict.SUPPORTED, Verdict.NOT_ENOUGH_EVIDENCE], Verdict.NOT_ENOUGH_EVIDENCE),
        ([Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR], Verdict.ERROR),
        ([Verdict.CONTRADICTED, Verdict.ERROR], Verdict.CONTRADICTED),
        ([Verdict.SUPPORTED, Verdict.SUPPORTED], Verdict.SUPPORTED),
    ],
)
def test_a_record_is_as_severe_as_its_worst_claim(claims, expected):
    assert aggregate(claims) is expected


def test_replay_answers_repeated_requests_and_never_invents_one(tmp_path):
    from inkloom_verify.evaluation.replay import ReplayMissError
    from inkloom_verify.providers.base import JsonCompletionRequest

    path = tmp_path / "c.jsonl"
    recorder = RecordingProvider(ScriptedProvider(), path)
    asked = JsonCompletionRequest(
        system="s",
        user="<verification_input_json>\n"
        + json.dumps({"claim": "x", "passages": []})
        + "\n</verification_input_json>",
        schema_name="claim_verification",
        json_schema={},
    )
    recorder.complete_json(asked)
    replay = ReplayProvider(path)
    assert (
        replay.complete_json(asked).data == replay.complete_json(asked).data
    )  # asked twice, same answer
    with pytest.raises(ReplayMissError):
        replay.complete_json(asked.model_copy(update={"user": asked.user + " "}))
    assert replay.misses == 1


def test_a_full_pipeline_run_reports_all_eight_metrics_from_its_own_outcomes(cassette):
    """EVAL.md Phase 4: review share and traceability come from this run's per-case outcomes."""
    _, out = cassette
    report, cases = read(out)
    m = report["required_metrics"]
    assert m["human_review_share"]["denominator"] == 80 == m["review"]["records_with_outcome"]
    routed = sum(1 for c in cases.values() if c["requires_human_review"])
    assert m["human_review_share"]["numerator"] == routed
    assert m["contradicted_precision"] is not None  # the scripted model flags the €99 claims
    attempts = sum(1 for c in cases.values() for claim in c["claims"] if claim["correction"])
    assert sum(m["corrections"]["attempts_by_status"].values()) == attempts
    assert "not model quality" in (out / "report.md").read_text(encoding="utf-8")
