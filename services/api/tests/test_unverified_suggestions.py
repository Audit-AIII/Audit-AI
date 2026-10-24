"""Safer-wording suggestions for UNVERIFIED claims - backend side (step 4b, handoff route).

The engine's softening step (inkloom_verify.softening.ClaimSoftener; product rules in
docs/backend.md, "Safer wording for unverified claims") is present. These tests pin the
backend side:

1. the engine's real softener is loaded, and end to end through it (scripted model, real engine
   checks, real backend guard) the handoff example is offered and the "leading" swap is not;
   -> test_engine_softener_is_loaded
   -> test_real_engine_softener_end_to_end (parametrised)
2. the guard (softening_guard.py) on the handoff's own examples: a good softening passes;
   swapping one ranking for another, adding a number, dropping a price/date/name, no change,
   hidden characters - all refused;
   -> test_guard_accepts_a_real_softening
   -> test_guard_refusals (parametrised)
3. with a softener present: the suggestion is stored as the whole rewritten claim, the finding
   stays unverified, the softening call is logged like any other model call;
   -> test_softener_suggestion_is_stored_and_finding_stays_unverified
4. a softener suggestion that breaks the rules is dropped; a softener crash changes nothing.
   -> test_rule_breaking_softener_suggestion_is_dropped
   -> test_softener_crash_keeps_review_intact
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import pytest
from inkloom_verify.providers.base import JsonCompletionRequest
from inkloom_verify.schemas import SourceSpan

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule
from inkloom_api.models import ExternalCallLog
from inkloom_api.softening_guard import softening_issues

KORA_FACTS = "Kora X2 - Product Fact Sheet\n\nCamera: 50 MP main camera.\nPrice: ₹24,999.\n"
CLAIM = "The Kora X2 is India's number one smartphone."


def test_engine_softener_is_loaded() -> None:
    from inkloom_verify.softening import ClaimSoftener

    from inkloom_api.engine.pipeline import load_softener_class

    assert load_softener_class() is ClaimSoftener


@pytest.mark.parametrize(
    "correction, expected",
    [
        (
            ("India's number one smartphone", "a smartphone sold in India"),
            "The Kora X2 is a smartphone sold in India.",
        ),
        (
            ("number one", "leading"),
            None,
        ),  # one unproven ranking for another: the engine refuses it
        (("India's number one smartphone", "a 5G smartphone sold in India"), None),  # invented fact
    ],
)
@requires_db
def test_real_engine_softener_end_to_end(
    client, monkeypatch, db_session, account_factory, correction, expected
) -> None:
    """No stand-in: the engine's own ClaimSoftener, prompt and checks, then the backend guard."""
    rule = ScriptedRule(
        "number one",
        "NOT_ENOUGH_EVIDENCE",
        None,
        "No document mentions rankings.",
        correction=correction,
    )
    use_scripted_provider(monkeypatch, [rule])
    owner = account_factory("owner", with_source=False)
    owner.upload_source(KORA_FACTS)

    review = owner.submit(CLAIM)
    [finding] = review["findings"]
    assert finding["verification_status"] == "unverified" and finding["evidence"] == []
    assert finding["safer_wording"] == expected
    assert finding["suggested_correction"] is None  # evidence-backed corrections only
    db_session.expire_all()
    calls = db_session.query(ExternalCallLog).filter_by(review_id=uuid.UUID(review["id"])).count()
    assert calls == 3  # extraction + verification + softening, all logged


def test_guard_accepts_a_real_softening() -> None:
    assert softening_issues(CLAIM, "The Kora X2 is a smartphone sold in India.") == []
    assert (
        softening_issues(
            "Launching 15 August at ₹24,999, the best Kora X2 deal.",
            "Launching 15 August at ₹24,999, a Kora X2 deal.",
        )
        == []
    )


@pytest.mark.parametrize(
    "original,rewritten,expected_prefix",
    [
        (
            CLAIM,
            "The Kora X2 is India's leading smartphone.",
            "unproven_ranking",
        ),  # one ranking -> another
        (CLAIM, "The Kora X2 is India's #1 smartphone.", "unproven_ranking"),
        (CLAIM, "The Kora X2 is the fastest smartphone in India.", "unproven_ranking"),
        (CLAIM, "The Kora X2 is the only smartphone made in India.", "unproven_ranking"),
        (
            CLAIM,
            "The Kora X2 is used by 10 million people in India.",
            "adds_numbers",
        ),  # invented fact
        (
            "The Kora X2 costs ₹24,999 and is the best phone.",
            "The Kora X2 is a phone.",
            "drops_number",
        ),
        ("Kora X2 ships 15 August, the best launch.", "Kora X2 ships soon.", "drops_number"),
        ("Out in August, the best Kora X2 yet.", "Out soon, a new Kora X2.", "drops_date"),
        (CLAIM, "It is a smartphone sold in India.", "drops_name"),  # product name lost
        (CLAIM, CLAIM, "no_change"),
        (CLAIM, "The Kora X2 is a smartphone‮ sold in India.", "hidden_characters"),
    ],
)
def test_guard_refusals(original: str, rewritten: str, expected_prefix: str) -> None:
    issues = softening_issues(original, rewritten)
    assert any(issue.startswith(expected_prefix) for issue in issues), issues


@dataclass(frozen=True)
class _Softened:
    target_span: SourceSpan
    original_text: str
    replacement_text: str


class _FakeSoftener:
    """Stands in for the engine's proposed `ClaimSoftener` (handoff interface): asks the provider
    (so the call is logged like any other) and returns target_span / original_text /
    replacement_text, or None."""

    def __init__(self, provider) -> None:
        self.provider = provider

    def soften(self, result, content):
        claim = result.claim
        sentence = claim.source_span.slice(content.text)
        reply = self.provider.complete_json(
            JsonCompletionRequest(
                system="soften (test double)",
                user="<softening_input_json>\n"
                + json.dumps({"sentence": sentence, "claim": claim.statement})
                + "\n</softening_input_json>",
                schema_name="claim_softening",
                json_schema={"type": "object"},
                max_output_tokens=256,
            )
        ).data
        if reply["status"] not in ("corrected", "softened"):
            return None
        start = sentence.index(reply["original_text"]) + claim.source_span.start
        return _Softened(
            SourceSpan(start=start, end=start + len(reply["original_text"])),
            reply["original_text"],
            reply["replacement_text"],
        )


def _with_softener(monkeypatch, softener_class) -> None:
    from inkloom_api.engine import pipeline

    monkeypatch.setattr(pipeline, "load_softener_class", lambda: softener_class)


@requires_db
def test_softener_suggestion_is_stored_and_finding_stays_unverified(
    client, monkeypatch, db_session, account_factory
) -> None:
    rule = ScriptedRule(
        "number one",
        "NOT_ENOUGH_EVIDENCE",
        None,
        "No document mentions rankings.",
        correction=("India's number one smartphone", "a smartphone sold in India"),
    )
    use_scripted_provider(monkeypatch, [rule])
    _with_softener(monkeypatch, _FakeSoftener)
    owner = account_factory("owner", with_source=False)
    owner.upload_source(KORA_FACTS)

    review = owner.submit(CLAIM)
    [finding] = review["findings"]
    assert finding["verification_status"] == "unverified"  # a suggestion never verifies the claim
    assert finding["category"] == "unsupported_claim"
    assert finding["safer_wording"] == "The Kora X2 is a smartphone sold in India."
    assert finding["suggested_correction"] is None  # evidence-backed corrections only
    assert finding["evidence"] == []
    db_session.expire_all()
    calls = db_session.query(ExternalCallLog).filter_by(review_id=uuid.UUID(review["id"])).count()
    assert calls == 3  # extraction + verification + softening, all logged


@requires_db
def test_rule_breaking_softener_suggestion_is_dropped(client, monkeypatch, account_factory) -> None:
    rule = ScriptedRule(
        "number one",
        "NOT_ENOUGH_EVIDENCE",
        None,
        "No document mentions rankings.",
        correction=("number one", "leading"),
    )  # one unproven ranking for another
    use_scripted_provider(monkeypatch, [rule])
    _with_softener(monkeypatch, _FakeSoftener)
    owner = account_factory("owner", with_source=False)
    owner.upload_source(KORA_FACTS)
    [finding] = owner.submit(CLAIM)["findings"]
    assert finding["verification_status"] == "unverified"
    assert finding["suggested_correction"] is None and finding["safer_wording"] is None


@requires_db
def test_softener_crash_keeps_review_intact(client, monkeypatch, account_factory) -> None:
    class _Crashing:
        def __init__(self, provider) -> None:
            pass

        def soften(self, result, content):
            raise RuntimeError("simulated softener bug")

    use_scripted_provider(
        monkeypatch, [ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No rankings.")]
    )
    _with_softener(monkeypatch, _Crashing)
    owner = account_factory("owner", with_source=False)
    owner.upload_source(KORA_FACTS)
    review = owner.submit(CLAIM)
    assert review["status"] == "needs_human_review"
    [finding] = review["findings"]
    assert (
        finding["verification_status"],
        finding["suggested_correction"],
        finding["safer_wording"],
    ) == ("unverified", None, None)
