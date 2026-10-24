"""A deterministic, offline stand-in for an LLM, for demo seeding and tests. Never a real model.

`scripted_provider(rules)` answers the engine's own prompts (claim extraction, claim verification,
correction) from keyword rules instead of a model, by reading the same JSON the engine sends a
real provider:

* extraction: every sentence becomes one factual claim, quoted verbatim;
* verification: the first rule whose `match` appears in the claim decides the verdict, and its
  `evidence` is quoted from whichever retrieved passage contains it - so the citation is real
  text of a real approved source, and this backend's own evidence validator checks it exactly as
  it would a model's (engine/evidence_validator.py). No rule, or evidence not in any passage:
  NOT_ENOUGH_EVIDENCE;
* correction / softening: the rule's `correction` (original, replacement) pair.

Every model id it reports starts with `scripted/`, and seeded content is labelled `[SEEDED]`, so a
scripted result is never mistaken for a real model's. It exists so `scripts/seed.py` needs no API
key and so tests can drive real CONTRADICTED / SUPPORTED outcomes through the real engine code
(retrieval, citation guard, corrector, re-check) without reverse-engineering passage ids.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from inkloom_verify.providers.base import JsonCompletionRequest
from inkloom_verify.providers.fake import ResponderProvider

SCRIPTED_MODEL_ID = "scripted/demo-v1"

_BLOCK = re.compile(r"<(\w+)>\n(.*)\n</\1>", re.DOTALL)


@dataclass(frozen=True)
class ScriptedRule:
    match: str  # case-insensitive substring of the claim being checked
    verdict: str  # "SUPPORTED" | "CONTRADICTED" | "NOT_ENOUGH_EVIDENCE"
    evidence: str | None = None  # verbatim text of an approved source, quoted as the citation
    rationale: str = "Scripted demo verdict."
    correction: tuple[str, str] | None = None  # (text to replace, replacement) when asked to fix


def _payload(request: JsonCompletionRequest) -> dict[str, Any]:
    match = _BLOCK.search(request.user)
    if match is None:
        raise ValueError("scripted provider: no JSON input block in the request")
    return json.loads(match.group(2))


def _rule_for(rules: list[ScriptedRule], text: str) -> ScriptedRule | None:
    folded = text.casefold()
    return next((rule for rule in rules if rule.match.casefold() in folded), None)


def _not_enough(rationale: str) -> dict[str, Any]:
    return {"verdict": "NOT_ENOUGH_EVIDENCE", "citations": [], "rationale": rationale}


def make_responder(rules: list[ScriptedRule]):
    def respond(request: JsonCompletionRequest) -> dict[str, Any]:
        data = _payload(request)
        if request.schema_name == "claim_extraction":
            return {
                "statements": [
                    {
                        "sentence_id": s["id"],
                        "kind": "factual",
                        "claims": [{"text": s["text"], "source_quote": s["text"]}],
                    }
                    for s in data["sentences"]
                ]
            }
        if request.schema_name == "claim_verification":
            rule = _rule_for(rules, data["claim"])
            if rule is None or rule.verdict == "NOT_ENOUGH_EVIDENCE" or rule.evidence is None:
                return _not_enough(rule.rationale if rule else "No approved source mentions this.")
            passage = next((p for p in data["passages"] if rule.evidence in p["text"]), None)
            if passage is None:
                return _not_enough("The retrieved passages do not contain the expected evidence.")
            return {
                "verdict": rule.verdict,
                "citations": [{"passage": passage["label"], "quote": rule.evidence}],
                "rationale": rule.rationale,
            }
        # Correction-shaped prompts: the contradicted-claim corrector and the unverified-claim
        # softener both reply with {status, original_text, replacement_text, citations, reason}.
        rule = _rule_for(rules, data.get("claim", "")) or _rule_for(rules, data.get("sentence", ""))
        if rule is None or rule.correction is None:
            return {
                "status": "needs_human_review",
                "original_text": "",
                "replacement_text": "",
                "citations": [],
                "reason": "No scripted correction for this claim.",
            }
        labels = [e["label"] for e in data.get("evidence", [])]
        return {
            # The engine's softener (inkloom_verify.softening) names its status "softened" and
            # cites nothing (there is no evidence for an unverified claim).
            "status": "softened" if request.schema_name == "claim_softening" else "corrected",
            "original_text": rule.correction[0],
            "replacement_text": rule.correction[1],
            "citations": labels[:1],
            "reason": "Scripted demo correction.",
        }

    return respond


def scripted_provider(rules: list[ScriptedRule]) -> ResponderProvider:
    """An `LLMProvider` (Member 2's protocol) answering from `rules`. See the module docstring."""
    return ResponderProvider(make_responder(rules), model=SCRIPTED_MODEL_ID)
