"""The public-contract fixtures (examples/public/, the repository's fixture location), Phase 5.

Every fixture is a complete public Report. It must validate against the model (with its request's
suggest_corrections) and the exported JSON Schema, and agree with the content and documents
recorded in fixtures.json. The mutation tests show each fixture passes because it is right, not
because validation is lenient: break the rule it demonstrates and it is rejected."""

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from inkloom_verify.api_contract import PUBLIC_SCHEMA_VERSION, Report

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "examples" / "public"
SCHEMA = json.loads((ROOT / "schemas" / "public_report.schema.json").read_text(encoding="utf-8"))
MANIFEST = {m["file"]: m for m in json.loads((PUBLIC / "fixtures.json").read_text(encoding="utf-8"))["fixtures"]}
FILES = ["supported.json", "contradicted.json", "not_enough_evidence.json", "error.json", "mixed_report.json"]


def load(name: str) -> dict:
    return json.loads((PUBLIC / name).read_text(encoding="utf-8"))


def validate(name: str, data: dict) -> Report:
    jsonschema.Draft202012Validator(SCHEMA).validate(data)
    return Report.model_validate(data, context={"suggest_corrections": MANIFEST[name]["suggest_corrections"]})


def statuses(report: Report) -> list[str]:
    return [e.verdict.status.value for e in report.claims]


# --- Every fixture: valid, versioned, consistent with its inputs ----------------------------------


def test_the_manifest_lists_exactly_the_fixtures():
    assert sorted(MANIFEST) == sorted(FILES)
    assert sorted(p.name for p in PUBLIC.glob("*.json")) == sorted(FILES + ["fixtures.json", "report.json"])


@pytest.mark.parametrize("name", FILES)
def test_fixture_is_a_valid_public_report(name):
    validate(name, load(name))


@pytest.mark.parametrize("name", FILES)
def test_every_model_carries_the_approved_schema_version(name):
    data = load(name)
    versions = [data["schema_version"]]
    for entry in data["claims"]:
        versions += [entry["claim"]["schema_version"], entry["verdict"]["schema_version"]]
        versions += [e["schema_version"] for e in entry["verdict"]["evidence"]]
        if entry["verdict"]["correction"]:
            versions += [e["schema_version"] for e in entry["verdict"]["correction"]["evidence"]]
    assert set(versions) == {PUBLIC_SCHEMA_VERSION}


@pytest.mark.parametrize("name", FILES)
def test_metadata_matches_the_agreed_contract(name):
    data, manifest = load(name), MANIFEST[name]
    assert set(data["metadata"]) == {"content_hash", "errors"}
    assert data["metadata"]["content_hash"] == hashlib.sha256(manifest["content"].encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", FILES)
def test_spans_and_quotes_point_at_the_real_text(name):
    report, manifest = validate(name, load(name)), MANIFEST[name]
    content, documents = manifest["content"], {d["doc_id"]: d["text"] for d in manifest["documents"]}
    for entry in report.claims:
        assert content[entry.claim.span.start:entry.claim.span.end] == entry.claim.text
        correction = entry.verdict.correction
        quotes = list(entry.verdict.evidence) + (list(correction.evidence) if correction else [])
        for item in quotes:
            assert documents[item.doc_id][item.location.start:item.location.end] == item.quote  # never invented
        if correction and correction.status.value == "proposed":
            assert content[correction.span.start:correction.span.end] == correction.original_text
            assert entry.claim.span.start <= correction.span.start and correction.span.end <= entry.claim.span.end
            assert correction.replacement_text in " ".join(e.quote for e in correction.evidence)


def test_fixtures_are_deterministic_fictional_data():
    for name in FILES:
        text = (PUBLIC / name).read_text(encoding="utf-8")
        assert "Lumen" in text or "lumen" in text  # the repository's fictional brand
        assert not any(marker in text for marker in ("http://", "https://", "@", "sk-"))


# --- What each fixture demonstrates ----------------------------------------------------------------


def test_supported_includes_evidence():
    report = validate("supported.json", load("supported.json"))
    assert statuses(report) == ["SUPPORTED"] and report.claims[0].verdict.evidence


def test_contradicted_includes_evidence_and_the_requested_correction():
    report = validate("contradicted.json", load("contradicted.json"))
    verdict = report.claims[0].verdict
    assert statuses(report) == ["CONTRADICTED"] and verdict.evidence and verdict.needs_human_review
    assert verdict.correction.status.value == "proposed" and verdict.correction.replacement_text == "€129"


def test_not_enough_evidence_invents_no_evidence():
    report = validate("not_enough_evidence.json", load("not_enough_evidence.json"))
    verdict = report.claims[0].verdict
    assert statuses(report) == ["NOT_ENOUGH_EVIDENCE"] and verdict.evidence == [] and verdict.confidence == 0.0


def test_error_follows_the_agreed_representation():
    report = validate("error.json", load("error.json"))
    verdict = report.claims[0].verdict
    assert statuses(report) == ["ERROR"] and verdict.error_code.value == "PROVIDER_TIMEOUT"
    assert verdict.evidence == [] and verdict.correction is None and verdict.needs_human_review


def test_mixed_report_keeps_successful_results_beside_failures():
    report = validate("mixed_report.json", load("mixed_report.json"))
    assert statuses(report) == ["SUPPORTED", "ERROR", "CONTRADICTED", "NOT_ENOUGH_EVIDENCE", "ERROR"]
    assert [e.verdict.error_code.value for e in report.claims if e.verdict.error_code] == ["PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMITED"]
    assert [e.claim.claim_id for e in report.claims] == [f"clm_{i:04d}" for i in range(1, 6)]
    singles = {"SUPPORTED": "supported.json", "CONTRADICTED": "contradicted.json", "NOT_ENOUGH_EVIDENCE": "not_enough_evidence.json"}
    for entry in report.claims:  # each successful result is the same verdict as in its single fixture
        if entry.verdict.status.value not in singles:
            continue
        name = singles[entry.verdict.status.value]
        single = validate(name, load(name)).claims[0]
        assert entry.verdict.model_dump(exclude={"correction"}) == single.verdict.model_dump(exclude={"correction"})
        if single.verdict.correction:  # the same correction; its span is in content coordinates, so it moves with the claim
            shift = entry.claim.span.start - single.claim.span.start
            mixed, alone = entry.verdict.correction, single.verdict.correction
            assert mixed.model_dump(exclude={"span"}) == alone.model_dump(exclude={"span"})
            assert (mixed.span.start, mixed.span.end) == (alone.span.start + shift, alone.span.end + shift)


# --- Mutations: break the rule, and the fixture is rejected ----------------------------------------


def mutated(name: str, change) -> dict:
    data = copy.deepcopy(load(name))
    change(data)
    return data


def first_verdict(data: dict) -> dict:
    return data["claims"][0]["verdict"]


@pytest.mark.parametrize(
    ("name", "change"),
    [
        ("supported.json", lambda d: first_verdict(d).update(evidence=[])),
        ("contradicted.json", lambda d: first_verdict(d).update(evidence=[])),
        ("contradicted.json", lambda d: first_verdict(d).update(correction=None)),  # requested but missing
        ("contradicted.json", lambda d: first_verdict(d).update(needs_human_review=False)),
        ("not_enough_evidence.json", lambda d: first_verdict(d).update(needs_human_review=False)),
        ("error.json", lambda d: first_verdict(d).update(error_code=None)),
        ("error.json", lambda d: first_verdict(d).update(evidence=load("supported.json")["claims"][0]["verdict"]["evidence"])),
        ("supported.json", lambda d: first_verdict(d).update(confidence=1.5)),
        ("supported.json", lambda d: first_verdict(d).update(status="PROBABLY")),
        ("supported.json", lambda d: d.update(schema_version="9.9.9")),
        ("supported.json", lambda d: d["claims"][0]["claim"].update(schema_version="0.0.1")),
        ("supported.json", lambda d: d["claims"][0]["claim"]["span"].update(end=0)),
        ("supported.json", lambda d: d["metadata"].update(extra_field=True)),
        ("mixed_report.json", lambda d: d["claims"][4]["claim"].update(claim_id="clm_0001")),
    ],
    ids=["supported-no-evidence", "contradicted-no-evidence", "contradicted-no-correction", "contradicted-no-review",
         "nee-no-review", "error-no-code", "error-with-evidence", "confidence-1.5", "unknown-status",
         "report-version", "claim-version", "empty-span", "metadata-extra", "duplicate-id"],
)
def test_breaking_the_rule_a_fixture_shows_is_rejected(name, change):
    with pytest.raises((ValidationError, jsonschema.ValidationError)):
        validate(name, mutated(name, change))


def test_an_invented_quote_is_caught_by_the_fixture_check():
    """The model cannot see documents; the fixture check can. A quote not in its document fails."""
    data = mutated("supported.json", lambda d: first_verdict(d)["evidence"][0].update(quote="up to 24 hours of playback per charge"))
    validate("supported.json", data)  # well-formed, so the contract alone accepts it...
    documents = {d["doc_id"]: d["text"] for d in MANIFEST["supported.json"]["documents"]}
    item = first_verdict(data)["evidence"][0]
    assert documents[item["doc_id"]][item["location"]["start"]:item["location"]["end"]] != item["quote"]  # ...this check does not


def test_without_requested_corrections_the_contradicted_fixture_must_drop_its_correction():
    with pytest.raises(ValidationError, match="no correction may be returned"):
        Report.model_validate(load("contradicted.json"), context={"suggest_corrections": False})
