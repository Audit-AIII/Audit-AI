"""One-command demo seed data for individual-user mode.

InkLoom is an individual-user app: one email = one private account, and each account can own
several brands. This seeds two demo users, each with their own account (organisation + one
`admin` membership, which now just means "account owner"), two brands, approved brand documents,
and demo content checked against them - enough for every page of the UI to show real rows:

* reviews in every decision state: completed, needs_human_review, approved, changes_requested;
* one content item with two versions (changes requested on v1, the fixed v2 decided again);
* one withdrawn brand document whose approved dependent flipped to source_changed (InkWatch);
* at least one "India's number one ..."-style claim with no evidence: flagged unverified;
* contradicted claims with an evidence-backed suggested rewrite (the engine's real corrector);
* timestamps spread over the last few days, so Insights has real turnaround and queue ages.

Demo reviews run through the offline scripted provider (src/inkloom_api/engine/scripted_provider.py),
never a real model, so seeding needs no API key and makes no network call. Its model id is
`scripted/demo-v1` and every seeded title/name is labelled [SEEDED], so seeded findings are never
mistaken for real AI output. The scripted verdicts still go through the real engine code path:
real retrieval, the engine's citation guard and corrector, and this backend's own evidence
validator. Decisions go through the same guards as the approve / request-changes routes.

Everything here is synthetic. No real customer data, no real secrets: the demo password below is
an intentionally obvious placeholder that protects nothing real.

Idempotent per user: a demo user whose email already exists is skipped entirely. `--reset`
deletes both demo accounts first (content, then account, then user - see `reset_user`) and
reseeds them from scratch.

Run from services/api, with the venv active and DATABASE_URL set (same as the test suite):
    .venv/Scripts/python scripts/seed.py            # seed (skips users that already exist)
    .venv/Scripts/python scripts/seed.py --reset    # delete the demo accounts and reseed
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from inkloom_verify.schemas import ReferenceDocument  # noqa: E402
from sqlalchemy import text  # noqa: E402

from inkloom_api.approval_service import check_approve_guards, record_decision  # noqa: E402
from inkloom_api.audit import log_audit_event  # noqa: E402
from inkloom_api.auth.security import hash_password  # noqa: E402
from inkloom_api.db import get_session_factory  # noqa: E402
from inkloom_api.engine.scripted_provider import ScriptedRule, scripted_provider  # noqa: E402
from inkloom_api.models import (  # noqa: E402
    BrandProfile,
    BrandSource,
    ContentItem,
    ContentVersion,
    Membership,
    Organisation,
    Review,
    SourceVersion,
    User,
)
from inkloom_api.review_runner import start_review  # noqa: E402
from inkloom_api.section_diff import document_section_hashes  # noqa: E402
from inkloom_api.source_lifecycle import withdraw_source  # noqa: E402
from inkloom_api.statuses import ApprovalAction, BrandSourceStatus, MembershipRole  # noqa: E402

# Synthetic, obviously-fake demo-only credential (documented in README.md) - not a real secret.
DEMO_PASSWORD = "SeedDemo!2026-not-a-real-secret"
SEED_TAG = "[SEEDED]"

APPROVE = "approve"
CHANGES = "changes_requested"


@dataclass
class DemoContent:
    title: str
    text: str
    decision: str | None = None  # APPROVE / CHANGES on the first version's review, or None (left open)
    # Later versions of the same item: (text, decision) - each runs its own review.
    revisions: list[tuple[str, str | None]] = field(default_factory=list)


@dataclass
class DemoBrand:
    name: str
    description: str
    sources: list[tuple[str, str]]  # (title, text) - all approved
    rules: list[ScriptedRule]
    content: list[DemoContent] = field(default_factory=list)
    # After the content: (source title, "superseded" | "archived", reason) - flips approved
    # dependents of that source to source_changed, exactly like POST .../withdraw.
    withdraw: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass
class DemoUser:
    email: str
    display_name: str
    account_name: str
    brands: list[DemoBrand]


# --- Brand documents and scripted verdicts --------------------------------------------------

LUMEN_FACTS = (
    "Lumen Pods - Product Fact Sheet (version 2, approved 2026-03-14)\n\n"
    "Battery life: up to 12 hours of playback per charge; up to 36 hours with the charging case.\n"
    "Charging: USB-C. A 10-minute charge gives up to 2 hours of playback.\n"
    "Water resistance: IPX4 (splash resistant). Not suitable for swimming.\n"
    "Price: €129 (EU launch price).\n"
    "Warranty: 2 years.\n"
)
LUMEN_GUIDE = (
    "Lumen Brand Guide (version 4)\n\n"
    "Voice: calm, precise and warm. Never use exclamation marks in headlines.\n"
    "Always refer to the product as 'Lumen Pods' - never 'earbuds' or 'headphones' in headlines.\n"
)
LUMEN_OLD_COLOURS = (
    "Lumen Pods - 2025 Colour Range (superseded by the 2026 range)\n\n"
    "Colours: Graphite, Sand, Teal.\n"
)
LUMEN = DemoBrand(
    name=f"Lumen Audio {SEED_TAG}",
    description="Synthetic demo brand: wireless earbuds sold in the EU.",
    sources=[
        ("Lumen Pods Product Fact Sheet", LUMEN_FACTS),
        ("Lumen Brand Guide", LUMEN_GUIDE),
        ("Lumen Pods 2025 Colour Range", LUMEN_OLD_COLOURS),
    ],
    rules=[
        ScriptedRule("24 hours of playback per charge", "CONTRADICTED", "up to 12 hours of playback per charge",
                     "The fact sheet gives up to 12 hours per charge, not 24.",
                     correction=("24 hours", "12 hours")),
        ScriptedRule("12 hours of playback per charge", "SUPPORTED", "up to 12 hours of playback per charge",
                     "The fact sheet states up to 12 hours of playback per charge."),
        ScriptedRule("waterproof", "CONTRADICTED", "Not suitable for swimming.",
                     "The fact sheet rates the product IPX4 splash resistant and not suitable for swimming."),
        ScriptedRule("warranty", "SUPPORTED", "Warranty: 2 years.", "The fact sheet states a 2-year warranty."),
        ScriptedRule("Graphite, Sand and Teal", "SUPPORTED", "Colours: Graphite, Sand, Teal.",
                     "The colour range lists Graphite, Sand and Teal."),
        ScriptedRule("best-selling", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions sales rankings."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Lumen Pods launch post",
                    "Lumen Pods offer up to 24 hours of playback per charge. Every pair comes with a 2-year warranty."),
        DemoContent(f"{SEED_TAG} Lumen Pods product page",
                    "Lumen Pods offer up to 12 hours of playback per charge. Lumen Pods come with a 2-year warranty.",
                    decision=APPROVE),
        DemoContent(f"{SEED_TAG} Lumen Pods colour announcement",
                    "Lumen Pods come in Graphite, Sand and Teal.", decision=APPROVE),
        DemoContent(f"{SEED_TAG} Lumen Pods summer ad",
                    "Lumen Pods are the best-selling earbuds in Europe. Lumen Pods are waterproof for any swim."),
    ],
    withdraw=[("Lumen Pods 2025 Colour Range", "superseded", "Replaced by the 2026 colour range.")],
)

KORA_FACTS = (
    "Kora X2 - Product Fact Sheet (approved 2026-07-01)\n\n"
    "Display: 6.5-inch AMOLED, 120 Hz.\n"
    "Battery: 5,000 mAh. Up to 2 days of typical use.\n"
    "Camera: 50 MP main camera.\n"
    "Price: ₹24,999 (India launch price).\n"
    "Launch date: 15 August 2026 in India.\n"
)
KORA = DemoBrand(
    name=f"Kora Phones {SEED_TAG}",
    description="Synthetic demo brand: a smartphone launched in India.",
    sources=[("Kora X2 Product Fact Sheet", KORA_FACTS)],
    rules=[
        ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None,
                     "None of the approved documents mention market rankings or sales position."),
        ScriptedRule("6,000 mAh", "CONTRADICTED", "Battery: 5,000 mAh.",
                     "The fact sheet gives a 5,000 mAh battery, not 6,000 mAh.",
                     correction=("6,000 mAh", "5,000 mAh")),
        ScriptedRule("5,000 mAh", "SUPPORTED", "Battery: 5,000 mAh.", "The fact sheet states a 5,000 mAh battery."),
        ScriptedRule("50 MP", "SUPPORTED", "Camera: 50 MP main camera.", "The fact sheet states a 50 MP main camera."),
        ScriptedRule("120 Hz", "SUPPORTED", "Display: 6.5-inch AMOLED, 120 Hz.", "The fact sheet states a 120 Hz display."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Kora X2 launch ad",
                    "The Kora X2 is India's number one smartphone. It has a 50 MP main camera."),
        DemoContent(f"{SEED_TAG} Kora X2 spec sheet copy",
                    "The Kora X2 packs a 6,000 mAh battery. It has a 50 MP main camera.",
                    decision=CHANGES,
                    revisions=[("The Kora X2 packs a 5,000 mAh battery. It has a 50 MP main camera.", APPROVE)]),
        # Left undecided and clean -> stays "completed". (Not "The Kora X2 has ...": the engine's
        # citation guard rightly refuses SUPPORTED when the claim has a number - the "2" of
        # "X2" - that the cited quote doesn't contain.)
        DemoContent(f"{SEED_TAG} Kora X2 display teaser",
                    "The Kora display runs at 120 Hz. It has a 50 MP main camera."),
    ],
)

VERDE_FACTS = (
    "Verde Steel Bottle - Fact Sheet (approved 2026-05-02)\n\n"
    "Keeps drinks cold for up to 24 hours and hot for up to 12 hours.\n"
    "Material: 70% recycled stainless steel.\n"
    "Capacity: 750 ml.\n"
    "Price: $34.\n"
)
VERDE_OLD_LID = (
    "Verde Bottle - Lid Spec (version 1, superseded)\n\n"
    "Lid: bamboo cap with a steel thread.\n"
)
VERDE = DemoBrand(
    name=f"Verde Bottles {SEED_TAG}",
    description="Synthetic demo brand: insulated steel bottles.",
    sources=[("Verde Steel Bottle Fact Sheet", VERDE_FACTS), ("Verde Lid Spec v1", VERDE_OLD_LID)],
    rules=[
        ScriptedRule("90% recycled", "CONTRADICTED", "Material: 70% recycled stainless steel.",
                     "The fact sheet gives 70% recycled stainless steel, not 90%.",
                     correction=("90%", "70%")),
        ScriptedRule("70% recycled", "SUPPORTED", "Material: 70% recycled stainless steel.",
                     "The fact sheet states 70% recycled stainless steel."),
        ScriptedRule("cold for up to 24 hours", "SUPPORTED", "Keeps drinks cold for up to 24 hours",
                     "The fact sheet states drinks stay cold for up to 24 hours."),
        ScriptedRule("bamboo", "SUPPORTED", "Lid: bamboo cap with a steel thread.", "The lid spec states a bamboo cap."),
        ScriptedRule("best-selling", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions sales rankings."),
        ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions rankings."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Verde summer campaign",
                    "The Verde bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled stainless steel."),
        DemoContent(f"{SEED_TAG} Verde marketplace listing",
                    "Verde is the best-selling steel bottle in Europe. The Verde bottle keeps drinks cold for up to 24 hours."),
        DemoContent(f"{SEED_TAG} Verde gift guide copy",
                    "The Verde bottle is made from 90% recycled stainless steel.",
                    decision=CHANGES,
                    revisions=[("The Verde bottle is made from 70% recycled stainless steel.", None)]),
        DemoContent(f"{SEED_TAG} Verde lid feature", "The Verde bottle has a bamboo cap.", decision=APPROVE),
    ],
    withdraw=[("Verde Lid Spec v1", "archived", "The bamboo cap was discontinued.")],
)

NIMBUS_FACTS = (
    "Nimbus Coffee - Product Facts (approved 2026-06-10)\n\n"
    "Origin: single-origin beans from Chikmagalur, India.\n"
    "Roast: medium.\n"
    "Certification: Fairtrade certified.\n"
    "Pack size: 250 g.\n"
)
NIMBUS = DemoBrand(
    name=f"Nimbus Coffee {SEED_TAG}",
    description="Synthetic demo brand: single-origin coffee.",
    sources=[("Nimbus Coffee Product Facts", NIMBUS_FACTS)],
    rules=[
        ScriptedRule("Fairtrade", "SUPPORTED", "Certification: Fairtrade certified.",
                     "The product facts state Fairtrade certification."),
        ScriptedRule("organic", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions organic certification."),
        ScriptedRule("number one", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions rankings."),
        ScriptedRule("250 g", "SUPPORTED", "Pack size: 250 g.", "The product facts state a 250 g pack."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Nimbus newsletter",
                    "Nimbus Coffee is Fairtrade certified. Every 250 g pack is roasted to order.", decision=APPROVE),
        DemoContent(f"{SEED_TAG} Nimbus shop banner",
                    "Nimbus Coffee is 100% organic. Nimbus Coffee is Fairtrade certified."),
        DemoContent(f"{SEED_TAG} Nimbus India launch post",
                    "Nimbus is India's number one coffee brand. Every 250 g pack is Fairtrade certified."),
        DemoContent(f"{SEED_TAG} Nimbus pack copy", "Nimbus Coffee is Fairtrade certified."),
    ],
)

DEMO_USERS = [
    DemoUser("asha@seed.inkloom.demo", f"Asha (demo) {SEED_TAG}", f"{SEED_TAG} Asha's account", [LUMEN, KORA]),
    DemoUser("ben@seed.inkloom.demo", f"Ben (demo) {SEED_TAG}", f"{SEED_TAG} Ben's account", [VERDE, NIMBUS]),
]


# --- Helpers ---------------------------------------------------------------------------------


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _Clock:
    """Hands out past timestamps, oldest first (~5 hours apart over the last few days), so the
    seeded data has a believable history: turnaround times and queue ages in Insights are then
    computed from these real rows like any others."""

    def __init__(self, start_hours_ago: float) -> None:
        self._at = datetime.now(timezone.utc) - timedelta(hours=start_hours_ago)

    def next(self, hours: float = 5.0) -> datetime:
        self._at += timedelta(hours=hours)
        return self._at


def _add_source(db, brand: BrandProfile, title: str, body: str, owner_id) -> BrandSource:
    source = BrandSource(
        brand_profile_id=brand.id, title=title, status=BrandSourceStatus.APPROVED.value,
        source_type="txt", created_by=owner_id,
    )
    db.add(source)
    db.flush()
    text_sha256 = _sha(body)
    db.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=body, text_sha256=text_sha256,
            section_hashes=document_section_hashes(
                ReferenceDocument(doc_id=str(source.id), text=body, text_sha256=text_sha256)
            ),
            created_by=owner_id,
        )
    )
    db.flush()
    return source


def _scripted(rules: list[ScriptedRule]):
    return [("scripted", lambda: scripted_provider(rules))]


def _review(db, org, owner, brand, demo: DemoBrand, version: ContentVersion, at: datetime, event: str) -> Review:
    review = start_review(db, version, brand.id, provider_builders=_scripted(demo.rules))
    review.created_at = at
    log_audit_event(
        db, organisation_id=org.id, actor_user_id=owner.id, event_type=event, entity_type="review",
        entity_id=review.id, details={"content_item_id": str(version.content_item_id), "seeded": True},
        request_id=review.request_id,
    )
    db.flush()
    return review


def _decide(db, org, owner, review: Review, version: ContentVersion, decision: str, at: datetime) -> None:
    """Exactly what the approve / request-changes routes do, through the same guards."""
    if decision == APPROVE:
        check_approve_guards(db, review, version.content_item_id)
        action, note = ApprovalAction.APPROVED, None
    else:
        action, note = ApprovalAction.CHANGES_REQUESTED, "Please fix the claims flagged in the review."
    event = record_decision(db, review, version, org.id, owner.id, action, note)
    db.flush()
    event.created_at = at
    db.flush()


def _submit(db, org, owner, brand, demo: DemoBrand, content: DemoContent, clock: _Clock) -> list[Review]:
    item = ContentItem(organisation_id=org.id, brand_profile_id=brand.id, title=content.title, created_by=owner.id)
    db.add(item)
    db.flush()
    reviews = []
    previous: ContentVersion | None = None
    for number, (body, decision) in enumerate([(content.text, content.decision)] + content.revisions, start=1):
        if previous is not None:
            previous.is_current = False
            db.flush()  # one current version per item (partial unique index)
        at = clock.next()
        version = ContentVersion(
            content_item_id=item.id, version_number=number, text=body, text_sha256=_sha(body),
            is_current=True, created_by=owner.id, created_at=at,
        )
        db.add(version)
        db.flush()
        review = _review(db, org, owner, brand, demo, version, at,
                         "review.submitted" if number == 1 else "content_version.created")
        if decision is not None:
            _decide(db, org, owner, review, version, decision, at + timedelta(minutes=45 + 30 * number))
        reviews.append(review)
        previous = version
    return reviews


def reset_user(db, email: str) -> None:
    """Deletes a demo user's account(s) and the user. Content goes first: deleting the
    organisation in one cascade makes Postgres run brand_sources' ON DELETE SET NULL on
    evidence_links rows the same cascade already removed through findings."""
    user = db.query(User).filter_by(email=email).first()
    if user is None:
        return
    org_ids = [m.organisation_id for m in db.query(Membership).filter_by(user_id=user.id).all()]
    for org_id in org_ids:
        db.execute(text("DELETE FROM content_items WHERE organisation_id = :id"), {"id": org_id})
        db.execute(text("DELETE FROM organisations WHERE id = :id"), {"id": org_id})
    db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})
    db.commit()
    print(f"{email}: reset (account and user deleted)")


def seed_user(db, demo: DemoUser, start_hours_ago: float) -> None:
    if db.query(User).filter_by(email=demo.email).first() is not None:
        print(f"{demo.email}: already seeded - skipped (use --reset to reseed).")
        return

    clock = _Clock(start_hours_ago)
    owner = User(email=demo.email, display_name=demo.display_name, password_hash=hash_password(DEMO_PASSWORD))
    org = Organisation(name=demo.account_name, slug=f"seed-{demo.email.split('@')[0]}")
    db.add_all([owner, org])
    db.flush()
    # One membership: this user is the account owner ("admin" now means exactly that).
    db.add(Membership(organisation_id=org.id, user_id=owner.id, role=MembershipRole.ADMIN.value, is_active=True))
    log_audit_event(db, organisation_id=org.id, actor_user_id=owner.id, event_type="account.registered",
                    entity_type="organisation", entity_id=org.id, details={"seeded": True})

    print(f"{demo.email}: account '{org.name}'")
    for demo_brand in demo.brands:
        brand = BrandProfile(organisation_id=org.id, name=demo_brand.name, description=demo_brand.description)
        db.add(brand)
        db.flush()
        sources = {title: _add_source(db, brand, title, body, owner.id) for title, body in demo_brand.sources}
        print(f"  brand '{brand.name}' ({brand.id}), {len(sources)} approved source(s)")
        for content in demo_brand.content:
            for review in _submit(db, org, owner, brand, demo_brand, content, clock):
                print(f"    {content.title} -> review {review.id} ({review.status})")
        for title, status, reason in demo_brand.withdraw:
            flipped = withdraw_source(db, sources[title], status, reason, org.id, owner.id)
            log_audit_event(db, organisation_id=org.id, actor_user_id=owner.id, event_type="brand_source.withdrawn",
                            entity_type="brand_source", entity_id=sources[title].id,
                            details={"new_status": status, "reason": reason, "dependents_flipped": len(flipped)})
            print(f"    withdrew '{title}' ({status}) -> {len(flipped)} approved item(s) now source_changed")
    db.commit()


def seed(reset: bool = False) -> None:
    db = get_session_factory()()
    try:
        if reset:
            for demo in DEMO_USERS:
                reset_user(db, demo.email)
        for index, demo in enumerate(DEMO_USERS):
            seed_user(db, demo, start_hours_ago=96 - 6 * index)
    finally:
        db.close()
    print(f"\nDemo password for both seeded users: {DEMO_PASSWORD!r}")
    for demo in DEMO_USERS:
        print(f"  {demo.email}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the two [SEEDED] individual demo accounts.")
    parser.add_argument("--reset", action="store_true", help="delete the demo accounts first, then reseed")
    seed(reset=parser.parse_args().reset)
