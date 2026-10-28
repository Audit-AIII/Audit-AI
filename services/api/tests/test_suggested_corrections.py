"""Suggested rewrites for CONTRADICTED claims (step 4a): the engine's own ClaimCorrector, recheck
on, behind this backend's evidence validation. All offline, through the scripted provider: the
real extractor, retriever, verifier, citation guard, corrector and re-check all run.

1. a valid proposal is stored as the whole rewritten claim span (what the UI swaps in), and
   every extra model call (correction + re-check) is in external_call_log;
   -> test_contradicted_claim_gets_claim_level_suggestion_and_calls_are_logged
2. a proposal the engine's deterministic checks reject (adds a number with no evidence) -> none;
   -> test_proposal_with_unsupported_number_is_dropped
3. a proposal that doesn't re-verify as SUPPORTED -> none;
   -> test_proposal_that_fails_recheck_is_dropped
4. a provider failure during correction keeps the verdict, no suggestion, no crash;
   -> test_correction_provider_failure_keeps_verdict
5. if backend validation downgrades the finding, its correction is dropped too;
   -> test_backend_validation_downgrade_drops_correction
6. supported and unverified claims make no correction call at all.
   -> test_no_correction_call_for_supported_or_unverified
"""

from __future__ import annotations

import uuid

from inkloom_verify.providers.base import ProviderUnavailableError
from inkloom_verify.providers.fake import ResponderProvider

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import SCRIPTED_MODEL_ID, ScriptedRule, make_responder
from inkloom_api.models import ExternalCallLog

CLAIM = "Lumen Pods offer up to 24 hours of playback per charge."
CONTRADICTED = ScriptedRule(
    "24 hours of playback per charge",
    "CONTRADICTED",
    "up to 12 hours of playback per charge",
    "The fact sheet gives 12 hours.",
    correction=("24 hours", "12 hours"),
)
SUPPORTED_12 = ScriptedRule(
    "12 hours of playback per charge",
    "SUPPORTED",
    "up to 12 hours of playback per charge",
    "The fact sheet states 12 hours.",
)


def _calls(db_session, review_id: str) -> list[ExternalCallLog]:
    db_session.expire_all()
    return db_session.query(ExternalCallLog).filter_by(review_id=uuid.UUID(review_id)).all()


def _only_finding(review: dict) -> dict:
    [finding] = review["findings"]
    return finding


@requires_db
def test_contradicted_claim_gets_claim_level_suggestion_and_calls_are_logged(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, [CONTRADICTED, SUPPORTED_12])
    owner = account_factory("owner")
    review = owner.submit(CLAIM)
    finding = _only_finding(review)
    assert finding["verification_status"] == "contradicted"
    assert (
        finding["suggested_correction"] == "Lumen Pods offer up to 12 hours of playback per charge."
    )
    # The UI does draft.replace(original_text, suggested_correction): that must give a sentence.
    assert review["text"].replace(finding["original_text"], finding["suggested_correction"]) == (
        "Lumen Pods offer up to 12 hours of playback per charge."
    )
    calls = _calls(db_session, review["id"])
    # extraction + verification + correction + re-check of the corrected claim
    assert len(calls) == 4
    assert {c.status for c in calls} == {"success"}
    assert {c.model_id for c in calls} == {SCRIPTED_MODEL_ID}


@requires_db
def test_proposal_with_unsupported_number_is_dropped(client, monkeypatch, account_factory) -> None:
    bad = ScriptedRule(
        CONTRADICTED.match,
        "CONTRADICTED",
        CONTRADICTED.evidence,
        "x",
        correction=("24 hours", "18 hours"),
    )
    use_scripted_provider(
        monkeypatch, [bad, ScriptedRule("18 hours", "SUPPORTED", CONTRADICTED.evidence)]
    )
    finding = _only_finding(account_factory("owner").submit(CLAIM))
    assert finding["verification_status"] == "contradicted"  # the verdict stands
    assert finding["suggested_correction"] is None  # "18" is in no cited quote


@requires_db
def test_proposal_that_fails_recheck_is_dropped(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(monkeypatch, [CONTRADICTED])  # no rule supports the corrected claim
    review = account_factory("owner").submit(CLAIM)
    assert _only_finding(review)["suggested_correction"] is None
    assert len(_calls(db_session, review["id"])) == 4  # the re-check ran and said no


@requires_db
def test_correction_provider_failure_keeps_verdict(
    client, monkeypatch, db_session, account_factory
) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    scripted = make_responder([CONTRADICTED, SUPPORTED_12])

    def respond(request):
        if request.schema_name == "claim_correction":
            return ProviderUnavailableError("simulated outage during correction")
        return scripted(request)

    monkeypatch.setattr(
        pipeline,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("scripted", lambda: ResponderProvider(respond, model=SCRIPTED_MODEL_ID))],
            on_attempt=on_attempt,
        ),
    )
    review = account_factory("owner").submit(CLAIM)
    finding = _only_finding(review)
    assert review["status"] == "needs_human_review"
    assert finding["verification_status"] == "contradicted"
    assert finding["suggested_correction"] is None
    statuses = sorted(c.status for c in _calls(db_session, review["id"]))
    assert statuses.count("error") >= 1  # the failed correction call is logged too


@requires_db
def test_backend_validation_downgrade_drops_correction(
    client, monkeypatch, account_factory
) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.evidence_validator import EvidenceIntegrityError, IntegrityErrorCode

    use_scripted_provider(monkeypatch, [CONTRADICTED, SUPPORTED_12])

    def reject(citations, lookup):
        raise EvidenceIntegrityError(IntegrityErrorCode.QUOTE_NOT_FOUND, citations[0])

    monkeypatch.setattr(pipeline, "validate_all", reject)
    finding = _only_finding(account_factory("owner").submit(CLAIM))
    assert finding["verification_status"] == "unverified"
    assert finding["category"] == "unsupported_claim"
    assert finding["suggested_correction"] is None
    assert finding["evidence"] == []


@requires_db
def test_no_correction_call_for_supported_or_unverified(
    client, monkeypatch, db_session, account_factory
) -> None:
    use_scripted_provider(
        monkeypatch, [SUPPORTED_12, ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE")]
    )
    review = account_factory("owner").submit(
        "Lumen Pods offer up to 12 hours of playback per charge. "
        "Lumen Pods are India's number one earbuds."
    )
    assert all(f["suggested_correction"] is None for f in review["findings"])
    # extraction + two verifications + one softening call for the unverified claim (the scripted
    # model declines it); no correction call for either claim.
    assert len(_calls(db_session, review["id"])) == 4
