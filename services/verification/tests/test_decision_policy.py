"""EVAL.md Phase 5: the decision policy (inkloom_verify.decision_policy) and its calibration.

Pipeline tests use a scripted model through the real pipeline (extraction, retrieval, verifier,
citation guard, policy). No model confidence exists anywhere, and none is invented."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from e2e_support import RoutedProvider, data_block, request
from inkloom_verify.evaluation.runner import load_records
from inkloom_verify.api_contract import to_public_report
from inkloom_verify.decision_policy import DecisionPolicy, describe, looks_compound, review_reasons
from inkloom_verify.evaluation.calibrate import CalibrationError, calibrate
from inkloom_verify.pipeline import PipelineConfig, verify_request
from inkloom_verify.schemas import ClaimResult, ClaimReviewReason as R, EvidenceStrength as S, ReviewReason, Verdict

ROOT = Path(__file__).resolve().parents[1]
# Every reference document of the canonical dataset (DOCS holds only the v1 ones).
ALL_DOCS = {d.doc_id: d for r in load_records(ROOT / "eval" / "dataset.jsonl") for d in r.references}
WEIGHT = "Weight: 5.2 g per earbud; charging case 48 g."
IPX4 = "Water resistance: IPX4 (splash resistant)."
USBC = "Charging: USB-C."


def model(verdict: str, *quotes: str, confidence: float | None = None):
    """Extraction: each sentence is one claim. Verification: ``verdict`` citing ``quotes``."""

    def respond(call):
        if call.schema_name == "claim_extraction":
            return {"statements": [{"sentence_id": s["id"], "kind": "factual", "claims": [{"text": s["text"], "source_quote": s["text"]}]}
                                   for s in data_block(call, "content_json")["sentences"]]}
        if call.schema_name == "claim_verification":
            passages = data_block(call, "verification_input_json")["passages"]
            citations = [{"passage": next(p["label"] for p in passages if q in p["text"]), "quote": q} for q in quotes]
            reply = {"verdict": verdict, "citations": citations, "rationale": "From the passages."}
            return reply | ({"confidence": confidence} if confidence is not None else {})
        return {"status": "needs_human_review", "original_text": "", "replacement_text": "", "citations": [], "reason": "No."}

    return respond


def run(content: str, respond, docs=("pods-fact-sheet",), policy: DecisionPolicy | None = None):
    config = PipelineConfig(decision_policy=policy or DecisionPolicy())
    req = request(content).model_copy(update={"references": [ALL_DOCS[d] for d in docs]})
    report = verify_request(req, RoutedProvider(respond), config)
    return report, report.results


# --- The cases EVAL.md lists, through the real pipeline --------------------------------------------


def test_a_clear_supported_claim_with_matched_figures_is_auto_cleared():
    report, [result] = run("Lumen Pods weigh 5.2 g per earbud.", model("SUPPORTED", WEIGHT))
    assert result.verdict is Verdict.SUPPORTED and result.evidence_strength is S.STRONG
    assert result.review_reasons == [] and result.requires_human_review is False
    assert report.score.requires_human_review is False


def test_a_clear_contradicted_claim_always_goes_to_a_person():
    _, [result] = run("Lumen Pods weigh 9 g per earbud.", model("CONTRADICTED", WEIGHT),
                      policy=DecisionPolicy(auto_clear_min_strength="moderate", compound_min_citations=1))  # even the loosest policy
    assert result.verdict is Verdict.CONTRADICTED and result.review_reasons == [R.CONTRADICTED] and result.requires_human_review


def test_insufficient_evidence_goes_to_a_person():
    _, [result] = run("Lumen Pods have active noise cancellation.", model("NOT_ENOUGH_EVIDENCE"))
    assert result.review_reasons == [R.NOT_ENOUGH_EVIDENCE] and result.requires_human_review


def test_a_missing_source_is_never_evidence_of_correctness():
    """The references say nothing about the claim: nothing is retrieved, the model is not asked,
    and the claim is NOT_ENOUGH_EVIDENCE, routed to a person (never SUPPORTED by default)."""
    provider_calls = []

    def respond(call):
        provider_calls.append(call.schema_name)
        return model("SUPPORTED", WEIGHT)(call)

    _, [result] = run("Lumen Pods weigh 5.2 g per earbud.", respond, docs=("brand-guide-v4",))
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.review_reasons == [R.NOT_ENOUGH_EVIDENCE]
    assert "claim_verification" not in provider_calls


def test_ambiguous_evidence_on_a_figure_free_claim_is_not_auto_cleared():
    """'All day' is vague; a model that calls it SUPPORTED on one quote cannot be checked by the
    figure checks. Under the default policy it goes to a person; only a looser policy clears it."""
    claim = "Lumen Pods keep their charge all day."
    quote = "Battery life: up to 12 hours of playback per charge; up to 36 hours with the charging case."
    _, [result] = run(claim, model("SUPPORTED", quote))
    assert result.verdict is Verdict.SUPPORTED and result.evidence_strength is S.MODERATE
    assert result.review_reasons == [R.BELOW_POLICY_STRENGTH] and result.requires_human_review
    _, [loose] = run(claim, model("SUPPORTED", quote), policy=DecisionPolicy(auto_clear_min_strength="moderate"))
    assert loose.requires_human_review is False  # documented trade-off of the looser setting


def test_conflicting_passages_are_handled_explicitly():
    _, [result] = run("Lumen Pods offer up to 12 hours of playback per charge.",
                      model("SUPPORTED", "Battery life: up to 12 hours of playback per charge"),
                      docs=("pods-fact-sheet", "pods-update-note"))
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.review_reasons == [R.NOT_ENOUGH_EVIDENCE]
    assert "conflicting_evidence" in [r.reason.value for r in result.citation_guard.rejected]


def test_a_partial_contradiction_in_one_claim_cannot_be_approved():
    """One clause right (5.2 g), one wrong (€99): the model calls it SUPPORTED on the weight quote,
    the support checks find €99 in no quote, and a person decides."""
    _, [result] = run("Lumen Pods weigh 5.2 g per earbud and cost €99.", model("SUPPORTED", WEIGHT))
    assert result.verdict is Verdict.NOT_ENOUGH_EVIDENCE and result.requires_human_review


def test_a_compound_claim_on_one_quote_is_not_auto_cleared():
    """'IPX4' is matched, so the evidence is STRONG; but the second clause is figure-free and
    uncited. The compound rule sends it to a person; with a quote for each clause it clears."""
    claim = "Lumen Pods are rated IPX4 and charge over USB-C."
    _, [one] = run(claim, model("SUPPORTED", IPX4))
    assert one.evidence_strength is S.STRONG and one.review_reasons == [R.COMPOUND_UNDER_CITED] and one.requires_human_review
    _, [two] = run(claim, model("SUPPORTED", IPX4, USBC))
    assert two.review_reasons == [] and two.requires_human_review is False


def test_one_contradicted_claim_makes_the_whole_report_need_review():
    report, results = run("Lumen Pods weigh 5.2 g per earbud. Lumen Pods cost €99.",
                          lambda call: model("CONTRADICTED" if "€99" in json.dumps(data_block(call, "verification_input_json"), ensure_ascii=False)
                                             else "SUPPORTED", "Price: €129 (EU launch price)." if "€99" in call.user else WEIGHT)(call)
                          if call.schema_name == "claim_verification" else model("SUPPORTED")(call))
    assert [r.verdict for r in results] == [Verdict.SUPPORTED, Verdict.CONTRADICTED]
    assert report.score.requires_human_review and ReviewReason.CONTRADICTED_CLAIMS in report.score.review_reasons


def test_missing_model_confidence_changes_nothing_and_a_supplied_one_is_refused():
    """No confidence is requested or used. A reply that carries one is not a valid reply."""
    _, [plain] = run("Lumen Pods weigh 5.2 g per earbud.", model("SUPPORTED", WEIGHT))
    assert plain.requires_human_review is False
    _, [confident] = run("Lumen Pods weigh 5.2 g per earbud.", model("SUPPORTED", WEIGHT, confidence=0.99))
    assert confident.verdict is Verdict.ERROR and confident.review_reasons == [R.ERROR]
    assert describe(DecisionPolicy())["uses_model_confidence"] is False
    with pytest.raises(ValidationError):
        DecisionPolicy(min_confidence=0.9)  # there is no confidence threshold to configure


def test_malformed_model_output_goes_to_a_person():
    def broken(call):
        if call.schema_name == "claim_verification":
            return {"verdict": "PROBABLY", "citations": [], "rationale": "x"}
        return model("SUPPORTED")(call)

    _, [result] = run("Lumen Pods weigh 5.2 g per earbud.", broken)
    assert result.verdict is Verdict.ERROR and result.review_reasons == [R.ERROR] and result.requires_human_review


def test_policy_routing_reaches_the_public_report_and_the_report_score():
    report, _ = run("Lumen Pods are rated IPX4 and charge over USB-C.", model("SUPPORTED", IPX4))
    assert ReviewReason.POLICY_THRESHOLD in report.score.review_reasons and report.score.requires_human_review
    [claim] = to_public_report(report).claims
    assert claim.verdict.needs_human_review is True


# --- Threshold boundaries, the decision function itself -------------------------------------------------


@pytest.mark.parametrize(("strength", "minimum", "expected"), [
    (S.STRONG, "strong", []), (S.MODERATE, "strong", [R.BELOW_POLICY_STRENGTH]),
    (S.MODERATE, "moderate", []), (S.STRONG, "moderate", []),
    (S.STRONG, "never", [R.BELOW_POLICY_STRENGTH]), (S.MODERATE, "never", [R.BELOW_POLICY_STRENGTH]),
    (S.WEAK, "moderate", [R.WEAK_EVIDENCE]), (S.WEAK, "strong", [R.WEAK_EVIDENCE]),  # the floor, never doubled
])
def test_auto_clear_strength_boundary(strength, minimum, expected):
    policy = DecisionPolicy(auto_clear_min_strength=minimum)
    assert review_reasons(Verdict.SUPPORTED, strength, "Lumen Pods weigh 5.2 g.", 1, policy) == expected


@pytest.mark.parametrize(("minimum", "citations", "routed"), [(2, 2, False), (2, 1, True), (1, 1, False), (3, 2, True), (3, 3, False)])
def test_compound_citation_boundary(minimum, citations, routed):
    policy = DecisionPolicy(compound_min_citations=minimum)
    reasons = review_reasons(Verdict.SUPPORTED, S.STRONG, "Lumen Pods weigh 5.2 g and cost €129.", citations, policy)
    assert (R.COMPOUND_UNDER_CITED in reasons) is routed


@pytest.mark.parametrize("verdict", [Verdict.CONTRADICTED, Verdict.NOT_ENOUGH_EVIDENCE, Verdict.ERROR])
def test_no_policy_adds_or_removes_reasons_for_non_supported_verdicts(verdict):
    for policy in (DecisionPolicy(auto_clear_min_strength="moderate", compound_min_citations=1),
                   DecisionPolicy(auto_clear_min_strength="never", compound_min_citations=3)):
        assert len(review_reasons(verdict, S.STRONG if verdict is Verdict.CONTRADICTED else S.NONE, "a and b", 0, policy)) == 1


@pytest.mark.parametrize("config", [
    {"auto_clear_min_strength": "weak"}, {"auto_clear_min_strength": "none"}, {"compound_min_citations": 0},
    {"compound_min_citations": 4}, {"compound_min_citations": "2"}, {"route_contradicted": False},
    {"version": "decision-policy-v0"},
], ids=["weak", "none", "zero", "four", "string", "switch-off-floor", "unknown-version"])
def test_no_configuration_can_loosen_the_floor(config):
    with pytest.raises(ValidationError):
        DecisionPolicy(**config)


@pytest.mark.parametrize(("text", "compound"), [
    ("Lumen Pods weigh 5.2 g and cost €129.", True), ("Rated IPX4; charges over USB-C.", True),
    ("Lumen Pods come in Graphite, Sand and Teal.", True),  # a list counts too: an extra review, never a missed one
    ("Lumen Pods weigh 5.2 g per earbud.", False), ("The Lumen Bottle is sandblasted.", False),
])
def test_compound_detection_is_deliberately_broad(text, compound):
    assert looks_compound(text) is compound


def test_the_contract_refuses_a_result_that_drops_a_floor_reason_or_misplaces_a_policy_reason():
    _, [contradicted] = run("Lumen Pods weigh 9 g per earbud.", model("CONTRADICTED", WEIGHT))
    data = contradicted.model_dump()
    for reasons, flag in (([], False), ([R.CONTRADICTED.value, R.COMPOUND_UNDER_CITED.value], True),
                          ([R.CONTRADICTED.value], False), ([R.CONTRADICTED.value, R.CONTRADICTED.value], True)):
        with pytest.raises(ValidationError):
            ClaimResult.model_validate(data | {"review_reasons": reasons, "requires_human_review": flag})


# --- Calibration: dev split only, safety before volume ----------------------------------------------------


def case_line(record_id, split, verdict, strength, citations=1, statement="Lumen Pods weigh 5.2 g per earbud."):
    claim = {"claim_id": "clm_0001", "text": statement, "statement": statement, "start": 0, "end": len(statement),
             "verdict": verdict, "evidence_strength": strength, "requires_human_review": True,
             "evidence": [], "citations": [{"doc_id": "d", "passage_id": "p", "quote": "q", "start": 0, "end": 1}] * citations,
             "guard_rejections": []}
    return json.dumps({"record_id": record_id, "split": split, "expected": "SUPPORTED", "predicted": verdict, "outcome": "correct",
                       "report_status": "COMPLETED", "report_errors": [], "requires_human_review": True, "claims": [claim],
                       "prompt_versions": {}, "models": [], "seconds": 0.0})


def run_dir(tmp_path, lines, model_quality=False):
    (tmp_path / "cases.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "report.json").write_text(json.dumps({"run": {"verdict_source": "replay"}, "verdicts": {"is_model_quality": model_quality}}),
                                          encoding="utf-8")
    return tmp_path


def dataset(tmp_path, labels: dict[str, tuple[str, str]]):
    """A dataset of real records whose labels and splits are set for the test."""
    base = [json.loads(l) for l in (ROOT / "eval" / "dataset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_verdict = {v: next(r for r in base if r["expected_verdict"] == v) for v in ("SUPPORTED", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE")}
    rows = [by_verdict[label] | {"record_id": rid, "split": split} for rid, (label, split) in labels.items()]
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def test_calibration_never_reads_the_heldout_split(tmp_path):
    data = dataset(tmp_path, {"r-1": ("SUPPORTED", "dev"), "r-2": ("SUPPORTED", "heldout")})
    lines = [case_line("r-1", "dev", "SUPPORTED", "strong"), '{"record_id": "r-2", "this line": "is never parsed"}']
    result = calibrate(run_dir(tmp_path, lines), data)
    assert result["dev_records_with_outcomes"] == 1 and result["heldout_records_read"] == 0
    with pytest.raises(CalibrationError, match="dev split only"):
        calibrate(run_dir(tmp_path, lines), data, split="heldout")


def test_calibration_puts_safety_before_review_volume(tmp_path):
    """A CONTRADICTED record that the model called SUPPORTED on moderate evidence: the 'moderate'
    candidates would clear it (fewer reviews), so they are unsafe and not chosen."""
    data = dataset(tmp_path, {"ok-1": ("SUPPORTED", "dev"), "ok-2": ("SUPPORTED", "dev"), "bad": ("CONTRADICTED", "dev")})
    lines = [case_line("ok-1", "dev", "SUPPORTED", "strong"), case_line("ok-2", "dev", "SUPPORTED", "strong"),
             case_line("bad", "dev", "SUPPORTED", "moderate")]
    result = calibrate(run_dir(tmp_path, lines), data)
    moderate = [c for c in result["candidates"] if c["policy"]["auto_clear_min_strength"] == "moderate"]
    assert all(c["auto_cleared_contradicted"] == ["bad"] and not c["safe"] for c in moderate)
    assert result["proposal"]["auto_clear_min_strength"] == "strong"  # safe, and fewer reviews than "never"
    assert result["valid_for_selection"] is False and "NOT VALID" in result["validity_note"]


def test_when_nothing_is_safe_every_claim_goes_to_a_person(tmp_path):
    data = dataset(tmp_path, {"bad": ("CONTRADICTED", "dev")})
    result = calibrate(run_dir(tmp_path, [case_line("bad", "dev", "SUPPORTED", "strong")], model_quality=True), data)
    assert all(not c["safe"] for c in result["candidates"] if c["policy"]["auto_clear_min_strength"] != "never")
    assert result["proposal"]["auto_clear_min_strength"] == "never" and "every claim goes to a person" in result["selection_rule"]
    assert result["valid_for_selection"] is True


def test_calibration_never_changes_the_active_policy(tmp_path):
    policy_file = ROOT / "eval" / "decision_policy.json"
    before = policy_file.read_bytes()
    data = dataset(tmp_path, {"ok": ("SUPPORTED", "dev")})
    calibrate(run_dir(tmp_path, [case_line("ok", "dev", "SUPPORTED", "strong")]), data)
    assert policy_file.read_bytes() == before


# --- Recorded in evaluation reports -----------------------------------------------------------------------


def test_reports_record_the_policy_version_thresholds_and_calibration_status(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("run_eval_p5", ROOT / "eval" / "run_eval.py")
    run_eval = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_eval)
    assert run_eval.main(["--out", str(tmp_path / "a")]) == 0
    recorded = json.loads((tmp_path / "a" / "report.json").read_text(encoding="utf-8"))["run"]["decision_policy"]
    assert recorded["policy"]["version"] == "decision-policy-v1"
    assert recorded["policy"]["thresholds"] == {"auto_clear_min_strength": "strong", "compound_min_citations": 2}
    assert recorded["calibration"]["status"] == "not calibrated" and recorded["policy"]["uses_model_confidence"] is False
    bad = tmp_path / "bad_policy.json"
    bad.write_text(json.dumps({"policy": {"auto_clear_min_strength": "weak"}}), encoding="utf-8")
    assert run_eval.main(["--policy", str(bad), "--out", str(tmp_path / "b")]) == 2
