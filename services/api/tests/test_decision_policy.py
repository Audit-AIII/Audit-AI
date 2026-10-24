"""The engine's decision policy (inkloom_verify.decision_policy, as verify_request applies it)
decides which SUPPORTED claims still need a person; the backend no longer clears every
SUPPORTED claim on its own (engine/pipeline.py, _with_decision_policy).

1. a single-fact SUPPORTED claim on strong evidence is cleared: the review completes;
2. a compound SUPPORTED claim ("... and ...") resting on one quote goes to a person, and so does
   the review - even though the verdict stays supported;
3. if the policy itself fails, the claim is reviewed (never silently cleared).
"""

from __future__ import annotations

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule

SINGLE = "Lumen Pods offer up to 12 hours of playback per charge."
COMPOUND = "Lumen Pods offer up to 12 hours of playback per charge and are splash resistant."
ONE_QUOTE = [ScriptedRule("12 hours of playback per charge", "SUPPORTED", "up to 12 hours of playback per charge",
                          "The fact sheet states 12 hours.")]


@requires_db
def test_single_fact_on_strong_evidence_is_cleared(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, ONE_QUOTE)
    review = account_factory("owner").submit(SINGLE)
    [finding] = review["findings"]
    assert (finding["verification_status"], finding["requires_human_review"]) == ("supported", False)
    assert finding["review_reasons"] == []
    assert review["status"] == "completed"


@requires_db
def test_compound_claim_on_one_quote_goes_to_a_person(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, ONE_QUOTE)
    review = account_factory("owner").submit(COMPOUND)
    [finding] = review["findings"]
    assert finding["verification_status"] == "supported"  # the verdict is unchanged...
    assert finding["requires_human_review"] is True  # ...but one quote doesn't settle two facts
    assert finding["review_reasons"] == ["compound_under_cited"]  # and the UI can say why
    assert review["status"] == "needs_human_review"


@requires_db
def test_a_failing_policy_sends_the_claim_to_a_person(client, monkeypatch, account_factory) -> None:
    from inkloom_api.engine import pipeline

    def broken(*args, **kwargs):
        raise RuntimeError("policy bug")

    use_scripted_provider(monkeypatch, ONE_QUOTE)
    monkeypatch.setattr(pipeline, "apply_policy", broken)
    review = account_factory("owner").submit(SINGLE)
    [finding] = review["findings"]
    assert (finding["verification_status"], finding["requires_human_review"]) == ("supported", True)
    assert finding["review_reasons"] == ["error"]  # reviewed, and never with an empty reason
    assert review["status"] == "needs_human_review"


@requires_db
def test_review_reasons_for_each_kind_of_finding(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, [
        ScriptedRule("24 hours of playback per charge", "CONTRADICTED", "up to 12 hours of playback per charge", "12 hours."),
        ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No rankings."),
    ])
    review = account_factory("owner").submit(
        "Lumen Pods offer up to 24 hours of playback per charge. Lumen Pods are India's number one earbuds. BUY NOW TODAY."
    )
    reasons = {f["category"]: f["review_reasons"] for f in review["findings"]}
    assert reasons["contradicted_claim"] == ["contradicted"]
    assert reasons["unsupported_claim"] == ["not_enough_evidence"]
    assert reasons["accessibility"] is None  # rule findings: not a claim decision


@requires_db
def test_stub_findings_have_no_review_reasons(client, force_stub_mode, account_factory) -> None:
    [stub] = account_factory("owner").submit(SINGLE)["findings"]
    assert stub["category"] == "stub" and stub["review_reasons"] is None
