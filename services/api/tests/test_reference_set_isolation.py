"""Phase 3 (single-user decision, DECISIONS.md decision 1): reference-set isolation inside ONE
account. A brand's reviews are checked only against that brand's own approved, current documents
- never another brand's of the same owner, never a withdrawn one - and the result cache can't
smuggle one brand's evidence into another brand's review. (Cross-ACCOUNT isolation is in
test_cross_account_isolation.py.)

One account owns brand X (fact sheet: 12 hours) and brand Y (fact sheet: 40 hours). The scripted
model only ever quotes Y's "40 hours" line, so any evidence it produces for brand X would have
to come from Y's document.

1. the engine is handed only the reviewed brand's approved documents;
2. brand X's review cites nothing of brand Y's: the quote isn't in X's documents, so the claim
   is unverified;
3. the same text for brand Y is analysed afresh (not served from X's cache entry) and cites Y;
4. the same text for brand X again IS served from cache (the cache is on) - still nothing of Y's;
5. once Y's document is withdrawn, Y's next review uses neither it nor the cached result.
"""

from __future__ import annotations

from conftest import DEFAULT_FACT_SHEET, requires_db, use_scripted_provider
from inkloom_api.engine.scripted_provider import ScriptedRule

CLAIM = "Lumen Pods offer up to 40 hours of playback per charge."
BRAND_Y_FACTS = (
    "Lumen Pods Max - Fact Sheet\n\nBattery life: up to 40 hours of playback per charge.\n"
)
QUOTES_Y = ScriptedRule(
    "playback per charge",
    "SUPPORTED",
    "up to 40 hours of playback per charge",
    "The fact sheet states 40 hours.",
)


def _cited_sources(review: dict) -> set[str]:
    return {e["source_id"] for f in review["findings"] for e in f["evidence"]}


def _statuses(review: dict) -> list[str]:
    return [f["verification_status"] for f in review["findings"]]


@requires_db
def test_each_brand_is_checked_only_against_its_own_documents(
    client, monkeypatch, account_factory
) -> None:
    from inkloom_api import review_runner

    use_scripted_provider(monkeypatch, [QUOTES_Y])
    owner = account_factory("owner")  # brand X, with DEFAULT_FACT_SHEET approved
    assert "40 hours" not in DEFAULT_FACT_SHEET
    brand_y = owner.create_brand("Brand Y")["id"]
    source_y = owner.upload_source(BRAND_Y_FACTS, brand_id=brand_y, title="Max facts")["id"]

    handed_to_engine: list[set[str]] = []
    real_build_corpus = review_runner.build_corpus

    def spy(entries):
        handed_to_engine.append({str(source.id) for source, _ in entries})
        return real_build_corpus(entries)

    monkeypatch.setattr(review_runner, "build_corpus", spy)

    # 1-2. Brand X: only X's document reaches the engine, and Y's quote can't be cited.
    x_first = owner.submit(CLAIM)
    assert handed_to_engine[-1] == {owner.source_id}
    assert source_y not in _cited_sources(x_first)
    assert _cited_sources(x_first) == set()
    assert _statuses(x_first) == ["unverified"]
    assert x_first["served_from_cache"] is False

    # 3. Brand Y, same text, same account: analysed afresh against Y's document.
    y_first = owner.submit(CLAIM, brand_id=brand_y)
    assert handed_to_engine[-1] == {source_y}
    assert y_first["served_from_cache"] is False
    assert _statuses(y_first) == ["supported"]
    assert _cited_sources(y_first) == {source_y}

    # 4. Brand X again: the cache is genuinely on - and still holds only X's outcome.
    x_again = owner.submit(CLAIM)
    assert x_again["served_from_cache"] is True
    assert _statuses(x_again) == ["unverified"] and _cited_sources(x_again) == set()

    # 5. Y's document withdrawn: Y's next review neither uses it nor replays the cached result.
    withdrawn = client.post(
        f"/api/brands/{brand_y}/sources/{source_y}/withdraw",
        json={"status": "archived", "reason": "discontinued"},
        headers=owner.headers,
    )
    assert withdrawn.status_code == 200, withdrawn.text
    y_after = client.post(
        "/api/reviews", json={"brand_id": brand_y, "text": CLAIM}, headers=owner.headers
    )
    assert y_after.status_code == 201, y_after.text
    y_after = y_after.json()
    assert handed_to_engine[-1] == set()
    assert y_after["served_from_cache"] is False
    assert y_after["status"] == "failed"  # no approved document left to check against
    assert _cited_sources(y_after) == set()
