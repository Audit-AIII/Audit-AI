"""Fields the UI already reads (step 3 of the individual-user plan). All additive.

1. Finding.category is set on real runs: contradicted_claim / unsupported_claim / supported_claim /
   engine_error; the stub keeps "stub"; a cached replay keeps the category.
   -> test_real_run_sets_category_for_every_verdict
   -> test_stub_category_unchanged
   -> test_cached_replay_keeps_categories
2. ReviewOut.brand_name; evidence.source_title and source_version_number (still the version
   that was cited after the source gets a new version).
   -> test_review_brand_name_and_evidence_source_fields
3. BrandOut.review_count / open_review_count / last_review_at: zeros and null with no reviews,
   real counts after, own account only; "open" excludes decided, stale and superseded reviews.
   -> test_brand_stats_empty_brand_is_zero_and_null
   -> test_brand_stats_counts_and_open_definition
"""

from __future__ import annotations

import io
from datetime import datetime

from inkloom_verify.providers.base import ProviderUnavailableError
from inkloom_verify.providers.fake import ResponderProvider

from conftest import requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import SCRIPTED_MODEL_ID, ScriptedRule, make_responder

RULES = [
    ScriptedRule(
        "24 hours of playback per charge",
        "CONTRADICTED",
        "up to 12 hours of playback per charge",
        "The fact sheet gives 12 hours.",
    ),
    ScriptedRule("warranty", "SUPPORTED", "Warranty: 2 years.", "The fact sheet states 2 years."),
    ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No document mentions rankings."),
]
MIXED_TEXT = (
    "Lumen Pods offer up to 24 hours of playback per charge. Lumen Pods come with a 2-year warranty. "
    "Lumen Pods are India's number one earbuds."
)


def _by_text(review: dict) -> dict[str, dict]:
    return {f["original_text"]: f for f in review["findings"]}


@requires_db
def test_real_run_sets_category_for_every_verdict(client, monkeypatch, account_factory) -> None:
    from inkloom_api.engine import pipeline
    from inkloom_api.engine.providers.fallback import FallbackProvider

    scripted = make_responder(RULES)

    def respond(request):
        if (
            request.schema_name == "claim_verification" and "purple" in request.user
        ):  # in the claim only, never in the fact sheet
            return ProviderUnavailableError("simulated provider outage for one claim")
        return scripted(request)

    monkeypatch.setattr(
        pipeline,
        "build_provider",
        lambda confidential=False, on_attempt=None: FallbackProvider(
            [("scripted", lambda: ResponderProvider(respond, model=SCRIPTED_MODEL_ID))],
            on_attempt=on_attempt,
        ),
    )
    owner = account_factory("owner")
    review = owner.submit(MIXED_TEXT + " Lumen Pods ship in purple boxes.")
    categories = {f["verification_status"]: f["category"] for f in review["findings"]}
    assert categories["contradicted"] == "contradicted_claim"
    assert categories["supported"] == "supported_claim"
    statuses = sorted((f["category"], f["verification_status"]) for f in review["findings"])
    assert ("unsupported_claim", "unverified") in statuses
    assert ("engine_error", "unverified") in statuses  # never contradicted, never "false"
    assert all(f["category"] is not None for f in review["findings"])


@requires_db
def test_stub_category_unchanged(client, force_stub_mode, account_factory) -> None:
    [finding] = account_factory("owner").submit()["findings"]
    assert finding["category"] == "stub"


@requires_db
def test_cached_replay_keeps_categories(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("owner")
    first = owner.submit(MIXED_TEXT)
    second = owner.submit(MIXED_TEXT)
    assert second["served_from_cache"] is True
    assert sorted(f["category"] for f in second["findings"]) == sorted(
        f["category"] for f in first["findings"]
    )


@requires_db
def test_review_brand_name_and_evidence_source_fields(client, monkeypatch, account_factory) -> None:
    use_scripted_provider(monkeypatch, RULES)
    owner = account_factory("owner")
    review = owner.submit(MIXED_TEXT)
    brands = client.get("/api/brands", headers=owner.headers).json()
    assert review["brand_name"] == brands[0]["name"]

    contradicted = next(f for f in review["findings"] if f["verification_status"] == "contradicted")
    [evidence] = contradicted["evidence"]
    assert evidence["source_title"] == "Fact Sheet"
    assert evidence["source_version_number"] == 1
    unverified = next(f for f in review["findings"] if f["verification_status"] == "unverified")
    assert unverified["evidence"] == []

    # A new version of the source: the old review still names the version it actually cited.
    new_version = client.post(
        f"/api/brands/{owner.brand_id}/sources/{owner.source_id}/versions",
        files={
            "file": (
                "facts.txt",
                io.BytesIO(b"Battery life: up to 10 hours.\nWarranty: 2 years.\n"),
                "text/plain",
            )
        },
        headers=owner.headers,
    )
    assert new_version.status_code == 201, new_version.text
    fetched = client.get(f"/api/reviews/{review['id']}", headers=owner.headers).json()
    refetched = next(f for f in fetched["findings"] if f["verification_status"] == "contradicted")
    assert refetched["evidence"][0]["source_version_number"] == 1
    assert fetched["brand_name"] == review["brand_name"]


@requires_db
def test_brand_stats_empty_brand_is_zero_and_null(client, force_stub_mode, account_factory) -> None:
    owner = account_factory("owner", with_source=False)
    [brand] = client.get("/api/brands", headers=owner.headers).json()
    assert (brand["review_count"], brand["open_review_count"], brand["last_review_at"]) == (
        0,
        0,
        None,
    )


@requires_db
def test_brand_stats_counts_and_open_definition(client, force_stub_mode, account_factory) -> None:
    owner, other = account_factory("owner"), account_factory("other")
    other.submit()  # another account's review must never be counted
    second_brand = owner.create_brand("Second brand")

    approved = owner.submit("First draft.")
    assert (
        client.post(
            f"/api/content-versions/{approved['content_version_id']}/approve", headers=owner.headers
        ).status_code
        == 201
    )
    waiting = owner.submit("Second draft.")  # needs_human_review -> open
    edited = owner.submit("Third draft.")
    new_version = client.post(
        f"/api/content/{edited['content_item_id']}/versions",
        json={"text": "Third draft, edited."},
        headers=owner.headers,
    )
    assert new_version.status_code == 201  # old v1 review is now stale -> not open; v2's is open
    rerun = client.post(f"/api/reviews/{waiting['id']}/rerun", headers=owner.headers)
    assert rerun.status_code == 201  # the rerun supersedes `waiting` -> only the rerun is open

    brands = {b["id"]: b for b in client.get("/api/brands", headers=owner.headers).json()}
    main = brands[owner.brand_id]
    assert main["review_count"] == 5  # approved, waiting, edited v1, edited v2, rerun
    assert main["open_review_count"] == 2  # edited v2 + rerun
    assert datetime.fromisoformat(main["last_review_at"]) == datetime.fromisoformat(
        rerun.json()["created_at"]
    )
    assert (
        brands[second_brand["id"]]["review_count"],
        brands[second_brand["id"]]["last_review_at"],
    ) == (0, None)


@requires_db
def test_contract_schemas_declare_every_field_a_real_review_returns(
    client, monkeypatch, account_factory
) -> None:
    """contract/schemas/*.json use additionalProperties: false - a real response must not carry a
    key they don't declare, and must carry every key they require (keeps the contract honest)."""
    import json
    from pathlib import Path

    contract = Path(__file__).resolve().parents[3] / "contract" / "schemas"
    review_schema = json.loads((contract / "review.schema.json").read_text(encoding="utf-8"))
    finding_schema = json.loads((contract / "finding.schema.json").read_text(encoding="utf-8"))
    evidence_schema = finding_schema["definitions"]["EvidenceLink"]

    use_scripted_provider(monkeypatch, RULES)
    review = account_factory("owner").submit(MIXED_TEXT)
    finding = next(f for f in review["findings"] if f["evidence"])
    for body, schema in (
        (review, review_schema),
        (finding, finding_schema),
        (finding["evidence"][0], evidence_schema),
    ):
        assert set(body) <= set(schema["properties"]), set(body) - set(schema["properties"])
        assert set(schema["required"]) <= set(body)
