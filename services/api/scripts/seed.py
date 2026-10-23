"""One-command demo seed data for individual-user mode.

InkLoom is an individual-user app: one email = one private account, and each account can own
several brands. This seeds two demo users, each with their own account (organisation + one
`admin` membership, which now just means "account owner"), two brands, approved brand documents,
and demo content checked against them.

Demo reviews run through the offline scripted provider (src/inkloom_api/engine/scripted_provider.py),
never a real model, so seeding needs no API key and makes no network call. Its model id is
`scripted/demo-v1` and every seeded title/name is labelled [SEEDED], so seeded findings are never
mistaken for real AI output. The scripted verdicts still go through the real engine code path:
real retrieval, the engine's citation guard, and this backend's own evidence validator.

Everything here is synthetic. No real customer data, no real secrets: the demo password below is
an intentionally obvious placeholder that protects nothing real.

Idempotent per user: a demo user whose email already exists is skipped entirely (delete that
user's organisation and the user to reseed them from scratch).

Run from services/api, with the venv active and DATABASE_URL set (same as the test suite):
    .venv/Scripts/python scripts/seed.py
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

from inkloom_verify.schemas import ReferenceDocument  # noqa: E402

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
    SourceVersion,
    User,
)
from inkloom_api.review_runner import start_review  # noqa: E402
from inkloom_api.section_diff import document_section_hashes  # noqa: E402
from inkloom_api.statuses import BrandSourceStatus, MembershipRole  # noqa: E402

# Synthetic, obviously-fake demo-only credential (documented in README.md) - not a real secret.
DEMO_PASSWORD = "SeedDemo!2026-not-a-real-secret"
SEED_TAG = "[SEEDED]"


@dataclass
class DemoContent:
    title: str
    text: str


@dataclass
class DemoBrand:
    name: str
    description: str
    sources: list[tuple[str, str]]  # (title, text) - all approved
    rules: list[ScriptedRule]
    content: list[DemoContent] = field(default_factory=list)


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
LUMEN = DemoBrand(
    name=f"Lumen Audio {SEED_TAG}",
    description="Synthetic demo brand: wireless earbuds sold in the EU.",
    sources=[("Lumen Pods Product Fact Sheet", LUMEN_FACTS), ("Lumen Brand Guide", LUMEN_GUIDE)],
    rules=[
        ScriptedRule("24 hours of playback per charge", "CONTRADICTED", "up to 12 hours of playback per charge",
                     "The fact sheet gives up to 12 hours per charge, not 24.",
                     correction=("24 hours", "12 hours")),
        ScriptedRule("12 hours of playback per charge", "SUPPORTED", "up to 12 hours of playback per charge",
                     "The fact sheet states up to 12 hours of playback per charge."),
        ScriptedRule("waterproof", "CONTRADICTED", "Not suitable for swimming.",
                     "The fact sheet rates the product IPX4 splash resistant and not suitable for swimming."),
        ScriptedRule("warranty", "SUPPORTED", "Warranty: 2 years.", "The fact sheet states a 2-year warranty."),
        ScriptedRule("best-selling", "NOT_ENOUGH_EVIDENCE", None,
                     "No approved document mentions sales rankings."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Lumen Pods launch post",
                    "Lumen Pods offer up to 24 hours of playback per charge. Every pair comes with a 2-year warranty."),
        DemoContent(f"{SEED_TAG} Lumen Pods product page",
                    "Lumen Pods offer up to 12 hours of playback per charge. Lumen Pods come with a 2-year warranty."),
    ],
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
    ],
    content=[
        DemoContent(f"{SEED_TAG} Kora X2 launch ad",
                    "The Kora X2 is India's number one smartphone. It has a 50 MP main camera."),
        DemoContent(f"{SEED_TAG} Kora X2 spec sheet copy",
                    "The Kora X2 packs a 6,000 mAh battery. It has a 50 MP main camera."),
    ],
)

VERDE_FACTS = (
    "Verde Steel Bottle - Fact Sheet (approved 2026-05-02)\n\n"
    "Keeps drinks cold for up to 24 hours and hot for up to 12 hours.\n"
    "Material: 70% recycled stainless steel.\n"
    "Capacity: 750 ml.\n"
    "Price: $34.\n"
)
VERDE = DemoBrand(
    name=f"Verde Bottles {SEED_TAG}",
    description="Synthetic demo brand: insulated steel bottles.",
    sources=[("Verde Steel Bottle Fact Sheet", VERDE_FACTS)],
    rules=[
        ScriptedRule("90% recycled", "CONTRADICTED", "Material: 70% recycled stainless steel.",
                     "The fact sheet gives 70% recycled stainless steel, not 90%.",
                     correction=("90%", "70%")),
        ScriptedRule("70% recycled", "SUPPORTED", "Material: 70% recycled stainless steel.",
                     "The fact sheet states 70% recycled stainless steel."),
        ScriptedRule("cold for up to 24 hours", "SUPPORTED", "Keeps drinks cold for up to 24 hours",
                     "The fact sheet states drinks stay cold for up to 24 hours."),
        ScriptedRule("best-selling", "NOT_ENOUGH_EVIDENCE", None, "No approved document mentions sales rankings."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Verde summer campaign",
                    "The Verde bottle keeps drinks cold for up to 24 hours. It is made from 90% recycled stainless steel."),
        DemoContent(f"{SEED_TAG} Verde marketplace listing",
                    "Verde is the best-selling steel bottle in Europe. The Verde bottle keeps drinks cold for up to 24 hours."),
    ],
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
        ScriptedRule("250 g", "SUPPORTED", "Pack size: 250 g.", "The product facts state a 250 g pack."),
    ],
    content=[
        DemoContent(f"{SEED_TAG} Nimbus newsletter",
                    "Nimbus Coffee is Fairtrade certified. Every 250 g pack is roasted to order."),
        DemoContent(f"{SEED_TAG} Nimbus shop banner",
                    "Nimbus Coffee is 100% organic. Nimbus Coffee is Fairtrade certified."),
    ],
)

DEMO_USERS = [
    DemoUser("asha@seed.inkloom.demo", f"Asha (demo) {SEED_TAG}", f"{SEED_TAG} Asha's account", [LUMEN, KORA]),
    DemoUser("ben@seed.inkloom.demo", f"Ben (demo) {SEED_TAG}", f"{SEED_TAG} Ben's account", [VERDE, NIMBUS]),
]


# --- Helpers ---------------------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _add_source(db, brand: BrandProfile, title: str, text: str, owner_id) -> BrandSource:
    source = BrandSource(
        brand_profile_id=brand.id, title=title, status=BrandSourceStatus.APPROVED.value,
        source_type="txt", created_by=owner_id,
    )
    db.add(source)
    db.flush()
    text_sha256 = _sha(text)
    db.add(
        SourceVersion(
            brand_source_id=source.id, version_number=1, text=text, text_sha256=text_sha256,
            section_hashes=document_section_hashes(
                ReferenceDocument(doc_id=str(source.id), text=text, text_sha256=text_sha256)
            ),
            created_by=owner_id,
        )
    )
    db.flush()
    return source


def _scripted(rules: list[ScriptedRule]):
    return [("scripted", lambda: scripted_provider(rules))]


def _submit(db, org: Organisation, owner: User, brand: BrandProfile, demo: DemoBrand, content: DemoContent):
    item = ContentItem(organisation_id=org.id, brand_profile_id=brand.id, title=content.title, created_by=owner.id)
    db.add(item)
    db.flush()
    version = ContentVersion(
        content_item_id=item.id, version_number=1, text=content.text, text_sha256=_sha(content.text),
        created_by=owner.id,
    )
    db.add(version)
    db.flush()
    review = start_review(db, version, brand.id, provider_builders=_scripted(demo.rules))
    log_audit_event(
        db, organisation_id=org.id, actor_user_id=owner.id, event_type="review.submitted", entity_type="review",
        entity_id=review.id, details={"content_item_id": str(item.id), "seeded": True}, request_id=review.request_id,
    )
    db.flush()
    return item, version, review


def seed_user(db, demo: DemoUser) -> None:
    if db.query(User).filter_by(email=demo.email).first() is not None:
        print(f"{demo.email}: already seeded - skipped (delete the user and their account to reseed).")
        return

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
        for title, text in demo_brand.sources:
            _add_source(db, brand, title, text, owner.id)
        print(f"  brand '{brand.name}' ({brand.id}), {len(demo_brand.sources)} approved source(s)")
        for content in demo_brand.content:
            _, _, review = _submit(db, org, owner, brand, demo_brand, content)
            print(f"    {content.title} -> review {review.id} ({review.status})")
    db.commit()


def seed() -> None:
    db = get_session_factory()()
    try:
        for demo in DEMO_USERS:
            seed_user(db, demo)
    finally:
        db.close()
    print(f"\nDemo password for both seeded users: {DEMO_PASSWORD!r}")
    for demo in DEMO_USERS:
        print(f"  {demo.email}")


if __name__ == "__main__":
    seed()
